# Resonantia

A vibe-first search across **games, films, and albums**. Describe a feeling ("a rainy night drive") and get matches through one shared embedding space, with a detail page and "more like this" for each item.

**Status:** milestones 1–4: scaffold, films end to end, games/albums/the worker, and search behavior (filters, layout, a detail page, "more like this", a full-text fallback). Search covers all three media types, with type toggles, decade chips and a real `/item/<id>` page. The LLM layer, abuse protection and deployment come later. The plan and the decision log are in [docs/SPEC.md](docs/SPEC.md).

## Prerequisites

- Docker with Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.12 is managed by uv)
- Node 24 and npm
- A free **Gemini API key** from Google AI Studio (keep the project free of any billing account)
- A free **TMDB read-access token** (TMDB account, API settings; use the long "API Read Access Token", not the short key)
- To load games: a free Twitch app (client ID and secret) from https://dev.twitch.tv/console. Create it as a Confidential client with redirect URL `http://localhost`.
- To load albums: a free Last.fm API key from https://www.last.fm/api/account/create (the shared secret is not needed), and a `CONTACT_EMAIL` (an email or a URL such as your repository) for the User-Agent MusicBrainz and Wikipedia require

## Quick start

```bash
cp .env.example .env        # set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, GEMINI_API_KEY, TMDB_READ_ACCESS_TOKEN
docker compose up --build
```

Open http://localhost:8080. The catalog is empty at first, so load some films (next section) before searching. `docker compose down` stops the stack; add `-v` to also delete the database.

## Load the catalog and search

Ingest runs on your machine against the database Compose publishes on `127.0.0.1`:

```bash
docker compose up -d db
cd backend
uv run --env-file ../.env python manage.py ingest_films --limit 50    # films from TMDB
uv run --env-file ../.env python manage.py ingest_games --limit 50    # games from IGDB
uv run --env-file ../.env python manage.py ingest_albums --limit 50   # albums from Last.fm and MusicBrainz
uv run --env-file ../.env python manage.py embed_items                # embed everything with Gemini
```

All of these are safe to re-run or interrupt. Start with 50 of each to check the setup, then raise the limit (a few hundred films gives meaningful results; the target is about 2,000 per type). Albums take about three to four seconds each, because MusicBrainz allows one request a second, and the command prints why any album was left out (for example, no MusicBrainz id, or not a studio album). Then search at http://localhost:8080 — type toggles and decade chips narrow the results, and clicking a result opens its detail page with "more like this" — or call the API directly: `curl 'http://localhost:8080/api/search/?q=a%20rainy%20night%20drive'`. Search covers films and games by default; check the Albums box (or add `&types=film,game,album`) to include them — see "Search quality" below for why they start off.

## The background worker

`docker compose up` also starts a `worker` service, which runs the same ingest and embedding code as background jobs (Procrastinate, on the same Postgres, with no extra broker). It is meant for small top-ups; the full ingest is easier on your machine. Queue a job and follow it:

```bash
docker compose exec web python manage.py enqueue_job ingest_games --limit 20
docker compose logs -f worker
```

The jobs are `ingest_films`, `ingest_games`, `ingest_albums` and `embed_pending`; an ingest job queues an embedding job when it finishes. The same job cannot wait in the queue twice, a temporary outage is retried a few times, and a rejected key fails at once. Unlike `web`, the worker receives your whole `.env`, because ingest calls TMDB, IGDB and Last.fm. `WORKER_CONCURRENCY` and `LOG_LEVEL` are in `.env.example`.

## Things to know

- **Gemini free tier.** Embedding is limited to about 1,000 requests a day (resets at midnight Pacific time), and every film and every search spends one request. `embed_items` stops cleanly when the quota runs out; run it again the next day. Google may use and review text sent on the free tier, which is why the search page tells visitors not to enter personal information.
- **TMDB.** Film data and posters come from TMDB for non-commercial use, with attribution. TMDB's terms do not allow caching its data for more than 6 months, and `ingest_films` warns when the catalog is getting old. Re-run it to refresh.
- **`.env` pitfalls.** Define each variable once (Docker Compose uses the last duplicate, `uv run --env-file` uses the first), and use only letters and digits in `POSTGRES_PASSWORD` (the two tools read `$`, `#`, quotes and backslashes differently). The database keeps the password it was first created with, so after changing it run `docker compose down -v`.
- **Source terms.** IGDB (games) is free for non-commercial use under the Twitch Developer Services Agreement, and Last.fm (album tags) is non-commercial only. Album summaries are from Wikipedia (CC BY-SA), and MusicBrainz core data is CC0. The footer credits TMDB, IGDB, Last.fm, MusicBrainz and the Cover Art Archive; an album's own Wikipedia credit is on its detail page. The decision log in the SPEC records what is still unchecked, including the exact wording IGDB's agreement requires.
- **No protection yet.** The search endpoint has no rate limits until milestone 6, so do not expose it to the internet.
- **Search quality.** Ranking is vibe similarity from a shared embedding space, not a curated recommendation engine, so an occasional odd match is expected, especially for "more like this" within a franchise (it can surface an unrelated item that happens to share genre and keyword words). Albums are left out of the default search: a small number of them turned out to be "hubs" that sit disproportionately close to many unrelated queries (confirmed live — one album was the nearest album match for 20% of a 500-film sample, regardless of what those films were about), crowding out real album matches. They are still fully searchable by checking the Albums box. Both this and the separate, weaker-for-mood-queries album text quality are open questions for the milestone 7 evaluation harness, in `docs/SPEC.md`'s decision log.

## Development

```bash
# Backend tests (database must be running: docker compose up -d db)
cd backend && uv run --env-file ../.env pytest

# Backend lint and format check
cd backend && uv run ruff check . && uv run ruff format --check .

# Frontend (run `npm ci` once)
cd frontend && npm run dev          # Vite dev server; needs the stack running for /api
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```

Tests use fixtures and never call live APIs. CI runs the same checks plus a stack smoke test. [CLAUDE.md](CLAUDE.md) has the full command list and project conventions.

## Layout

| Path | What |
|---|---|
| `backend/catalog/` | Items, the film, game and album sources, embedding adapter, ingest and embed commands, background jobs (`tasks.py`), search, filters, layout, full-text fallback, item detail |
| `backend/core/` | Health endpoint |
| `backend/config/` | Django settings (environment only) and URLs |
| `frontend/` | React + Vite + TypeScript + Tailwind: search page with filters, item detail page, a small hand-rolled router |
| `caddy/` | Caddy config and the image that serves the built frontend |
| `compose.yaml` | `db` (Postgres + pgvector), `web` (gunicorn), `worker` (background jobs), `caddy` |
| `docs/SPEC.md` | Source of truth: requirements, milestones, decision log |

Film data and images are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB. Game data is from IGDB. Album tags are from Last.fm, album details from MusicBrainz, covers from the Cover Art Archive, and summaries from Wikipedia.
