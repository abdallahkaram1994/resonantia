# Resonantia — instructions for Claude Code

Resonantia is a vibe-first search across **games, films, and albums**. A visitor describes a feeling and gets matches from all three media types via one shared embedding space, with a detail page and "more like this" for each item.

**`docs/SPEC.md` is the source of truth.** Read it before starting any task. If a request conflicts with it, stop and ask. Propose an edit to the decision log instead of silently deviating.

## Working agreement

- Work on **one milestone at a time** (see the SPEC). Stop at the end of each and summarize what changed, what was tested, and what is left.
- Prefer small, reviewable changes: one focused branch and PR per slice.
- **Ask before adding a dependency.** State what it is for and why the standard library or an existing dependency is not enough.
- **Ask questions rather than guess** when a requirement is ambiguous. Do not write code for an unclear requirement.
- Do not refactor unrelated code or change decisions recorded in the SPEC without asking.
- Keep `docs/SPEC.md`, `.env.example`, and the README in sync with what you build.

## Hard constraints

- **Total budget is ≤ $60/year.** No paid services, no usage-billed services, no Redis, no managed databases. Never suggest attaching billing to an AI provider key.
- **Official, free APIs only.** No scraping, no unofficial APIs (HowLongToBeat, direct Rotten Tomatoes/Metacritic).
- **Respect source terms.** TMDB data is non-commercial only, needs the TMDB logo and non-endorsement notice, and must not be cached longer than 6 months. Do not commit real third-party content: fixtures use invented records in the provider's response shape. Check a new source's terms for AI use before building on it.
- **No ML model on our server.** Embeddings and LLM calls go through hosted free-tier APIs behind provider interfaces.
- **Anonymous v1.** No accounts, no personal data stored or sent to any AI provider.
- **Ranking is vibe similarity only, for every media type.** Ratings are display-only and are never embedded. A per-type quality weight exists in config, default `0`.
- Every filter is scoped by media type. A type-scoped filter must never affect another type's rows.

## Architecture in brief

- **Backend:** Python 3.12+, Django + DRF, Postgres with `pgvector`.
- **Background jobs:** **Procrastinate** (Postgres-backed). Do not use Celery or add Redis or any other broker. The `worker` container runs from the same image as `web`. See SPEC section 9b for the task list.
- **Worker rules:** tasks are idempotent and retry with backoff; use separate queues (`ingest`, `maintenance`); MusicBrainz work must honor ~1 request/second; tasks that call Gemini share the global circuit breaker; the search request path stays synchronous.
- **Frontend:** React + Vite + TypeScript + Tailwind, built to static files.
- **Runtime:** Docker Compose with `db`, `web`, `worker`, `caddy`. Cloudflare in front in production.
- **Provider adapters:** each data source implements a common interface so a source can be dropped or swapped. The LLM and the embedder are also interfaces (`parse_query`, `rerank_and_explain`, `embed`).
- **Provenance:** every sourced field stores `source` and `fetched_at`.
- **Search path:** normalize → cache → LLM parse → embed → pgvector retrieve with filters in SQL → rerank+explain → layout. Max two LLM calls per uncached search.
- **Fallbacks:** LLM down → embedding-only. Embedding/budget down → cached results, then Postgres full-text search.

## Conventions

- Python: type hints, `ruff` for lint and format, `pytest`. Use `uv` for dependencies.
- Keep API keys, model names, rate limits, and thresholds in config, not in code.
- Store the embedding model and dimension per item. Never compare vectors from different models.
- Timestamps are UTC. Store `release_year` as an integer (nullable).
- Descriptive User-Agent (with a contact email from config) on MusicBrainz and Wikipedia requests. Respect MusicBrainz's ~1 request/second.
- Commit messages: short, imperative, one logical change each.

## Commands

Keep this section current. Run from the repo root unless a `cd` is shown. Prerequisites: Docker with Compose, `uv`, Node 24.

**Setup (once):** `cp .env.example .env`, then set `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `GEMINI_API_KEY` and `TMDB_READ_ACCESS_TOKEN`. To load games also set `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`; to load albums set `LASTFM_API_KEY` and `CONTACT_EMAIL` (goes into the MusicBrainz and Wikipedia User-Agent). Compose refuses to start and names any required variable that is missing. Define each variable once (Compose uses the last duplicate, `uv run --env-file` the first) and use letters and digits only in `POSTGRES_PASSWORD`. The database keeps its first password, so after changing it run `docker compose down -v`.

**Start the stack:** `docker compose up --build`, then open http://localhost:8080 (Caddy serves the built frontend and proxies `/api` to Django). Stop with `docker compose down`; add `-v` to also delete the database volume.

**Migrations:** `web` runs `manage.py migrate` on every start, so `docker compose up` applies them. Manually: `docker compose run --rm web python manage.py migrate`.

**Load the catalog** (host, against the loopback database; `docker compose up -d db` first; all are resumable and idempotent). Run from `backend/`; the limit is `--limit`, else `INGEST_LIMIT`, else `CATALOG_TARGET_PER_TYPE`:
- `uv run --env-file ../.env python manage.py ingest_films --limit 50` fetches films from TMDB and warns when catalog data nears TMDB's 6-month limit.
- `... ingest_games --limit 50` fetches main games from IGDB (Twitch OAuth).
- `... ingest_albums --limit 50 [--retry-skipped]` finds albums on Last.fm, identifies them at MusicBrainz by id, and adds covers and Wikipedia summaries. About 3 to 4 seconds per album. It prints why albums were left out; `--retry-skipped` re-checks ones rejected earlier.
- `... embed_items [--limit N]` embeds pending items of every type with Gemini. The free tier allows about 1,000 requests a day, so it stops cleanly when the quota runs out; run it again the next day.
- Search (films only until M4): `curl 'http://localhost:8080/api/search/?q=a%20rainy%20night%20drive'` (spends one embedding request).

**Worker** (`worker` service, started by `docker compose up`; needs `web` healthy first): `docker compose exec web python manage.py enqueue_job <ingest_films|ingest_games|ingest_albums|embed_pending> [--limit N]`, then `docker compose logs -f worker`. The same job cannot wait in the queue twice. Health: `docker compose exec worker python manage.py procrastinate healthchecks`. Settings: `WORKER_CONCURRENCY`, `LOG_LEVEL`.

**Backend tests** (needs the database: `docker compose up -d db`):
`cd backend && uv run --env-file ../.env pytest`

**Backend lint:** `cd backend && uv run ruff check . && uv run ruff format --check .` (fix formatting with `uv run ruff format .`).

**Frontend** (`cd frontend`; run `npm ci` first):
- Dev server: `npm run dev`. It proxies `/api` to Caddy on `localhost:8080`, so start the stack first.
- Tests: `npm test`. Lint: `npm run lint`. Typecheck: `npm run typecheck`. Build: `npm run build`.

**CI** (`.github/workflows/ci.yml`) runs the backend checks, the frontend checks, and a stack smoke test (build, start, `/api/health/` and `/` through Caddy, and a queued `embed_pending` job that the worker must finish).

**Not implemented yet:**
- Search across all three types, filters and layout: M4. (`/api/search/` returns films only.)
- Periodic worker jobs (pruning, refresh, pre-warming): M6.
- Evaluation harness: M7.

## Testing rules

- **Tests never call live APIs.** Use fixtures (recorded, or invented in the provider's shape when the content is third-party) so tests need no keys and no network.
- Cover the behaviors that are easy to get wrong: filter isolation across media types, null-year handling, layout rules, per-type score normalization, fallback paths under forced failures, rate limits, cache-key versioning, and prompt-injection queries.
- New behavior needs a test. Bug fixes need a regression test.
- The golden-set evaluation runs against cached embeddings and must not spend quota in CI.

## Security and secrets

- **Never read, print, or commit `.env` or any secret.** Read configuration from environment variables only. `.env` stays gitignored; maintain `.env.example` with placeholders.
- The LLM receives only the user's query and stored item metadata, has **no tools**, and its output is validated against a strict schema before use.
- Treat all query text and all third-party API text as untrusted input.
- Never log search query text, and never return provider error details to visitors (log them; return a generic message).
- Read the client IP from `CF-Connecting-IP` **only** when the request comes from Cloudflare's published ranges.
- Admin and ingest endpoints are never publicly routable.
- Never store or proxy source images; hotlink from the source CDN and show attribution.

## Definition of done

- Tests pass and lint passes locally and in CI.
- Behavior matches the SPEC, or the SPEC is updated with the reason.
- `.env.example`, README, and this file are updated if anything they describe changed.
- The change is small enough for a human to review, and the summary says what to check.