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

**Setup (once):** `cp .env.example .env`, then set `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`. Compose refuses to start and names any required variable that is missing.

**Start the stack:** `docker compose up --build`, then open http://localhost:8080 (Caddy serves the built frontend and proxies `/api` to Django). Stop with `docker compose down`; add `-v` to also delete the database volume.

**Migrations:** `web` runs `manage.py migrate` on every start, so `docker compose up` applies them. Manually: `docker compose run --rm web python manage.py migrate`.

**Backend tests** (needs the database: `docker compose up -d db`):
`cd backend && uv run --env-file ../.env pytest`

**Backend lint:** `cd backend && uv run ruff check . && uv run ruff format --check .` (fix formatting with `uv run ruff format .`).

**Frontend** (`cd frontend`; run `npm ci` first):
- Dev server: `npm run dev`. It proxies `/api` to Caddy on `localhost:8080`, so start the stack first.
- Tests: `npm test`. Lint: `npm run lint`. Typecheck: `npm run typecheck`. Build: `npm run build`.

**CI** (`.github/workflows/ci.yml`) runs the backend checks, the frontend checks, and a stack smoke test (build, start, `/api/health/` and `/` through Caddy).

**Not implemented yet:**
- Sample ingest (`INGEST_LIMIT=50`): arrives with films in M2 and the worker in M3.
- Evaluation harness: arrives in M7.

## Testing rules

- **Tests never call live APIs.** Use recorded fixtures so tests need no keys and no network.
- Cover the behaviors that are easy to get wrong: filter isolation across media types, null-year handling, layout rules, per-type score normalization, fallback paths under forced failures, rate limits, cache-key versioning, and prompt-injection queries.
- New behavior needs a test. Bug fixes need a regression test.
- The golden-set evaluation runs against cached embeddings and must not spend quota in CI.

## Security and secrets

- **Never read, print, or commit `.env` or any secret.** Read configuration from environment variables only. `.env` stays gitignored; maintain `.env.example` with placeholders.
- The LLM receives only the user's query and stored item metadata, has **no tools**, and its output is validated against a strict schema before use.
- Treat all query text and all third-party API text as untrusted input.
- Read the client IP from `CF-Connecting-IP` **only** when the request comes from Cloudflare's published ranges.
- Admin and ingest endpoints are never publicly routable.
- Never store or proxy source images; hotlink from the source CDN and show attribution.

## Definition of done

- Tests pass and lint passes locally and in CI.
- Behavior matches the SPEC, or the SPEC is updated with the reason.
- `.env.example`, README, and this file are updated if anything they describe changed.
- The change is small enough for a human to review, and the summary says what to check.