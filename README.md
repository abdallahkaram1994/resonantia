# Resonantia

A vibe-first search across **games, films, and albums**. Describe a feeling ("a rainy night drive") and get matches through one shared embedding space, with a detail page and "more like this" for each item.

**Status:** milestones 1 (scaffold) and 2 (films end to end). You can load a film catalog and search it by feeling in the browser. Games and albums, filters, the LLM layer, abuse protection and deployment come later. The plan and the decision log are in [docs/SPEC.md](docs/SPEC.md).

## Prerequisites

- Docker with Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.12 is managed by uv)
- Node 24 and npm
- A free **Gemini API key** from Google AI Studio (keep the project free of any billing account)
- A free **TMDB read-access token** (TMDB account, API settings; use the long "API Read Access Token", not the short key)

## Quick start

```bash
cp .env.example .env        # set DJANGO_SECRET_KEY, POSTGRES_PASSWORD, GEMINI_API_KEY, TMDB_READ_ACCESS_TOKEN
docker compose up --build
```

Open http://localhost:8080. The catalog is empty at first, so load some films (next section) before searching. `docker compose down` stops the stack; add `-v` to also delete the database.

## Load films and search

Ingest runs on your machine against the database Compose publishes on `127.0.0.1`:

```bash
docker compose up -d db
cd backend
uv run --env-file ../.env python manage.py ingest_films --limit 50   # fetch films from TMDB
uv run --env-file ../.env python manage.py embed_items               # embed them with Gemini
```

Both commands are safe to re-run or interrupt. Start with 50 films to check the setup, then raise the limit (a few hundred films gives meaningful results; the target catalog is about 2,000). Then search at http://localhost:8080, or call the API directly: `curl 'http://localhost:8080/api/search/?q=a%20rainy%20night%20drive'`.

## Things to know

- **Gemini free tier.** Embedding is limited to about 1,000 requests a day (resets at midnight Pacific time), and every film and every search spends one request. `embed_items` stops cleanly when the quota runs out; run it again the next day. Google may use and review text sent on the free tier, which is why the search page tells visitors not to enter personal information.
- **TMDB.** Film data and posters come from TMDB for non-commercial use, with attribution. TMDB's terms do not allow caching its data for more than 6 months, and `ingest_films` warns when the catalog is getting old. Re-run it to refresh.
- **`.env` pitfalls.** Define each variable once (Docker Compose uses the last duplicate, `uv run --env-file` uses the first), and use only letters and digits in `POSTGRES_PASSWORD` (the two tools read `$`, `#`, quotes and backslashes differently). The database keeps the password it was first created with, so after changing it run `docker compose down -v`.
- **No protection yet.** The search endpoint has no rate limits until milestone 6, so do not expose it to the internet.

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
| `backend/catalog/` | Items, TMDB source, embedding adapter, ingest and embed commands, search |
| `backend/core/` | Health endpoint |
| `backend/config/` | Django settings (environment only) and URLs |
| `frontend/` | React + Vite + TypeScript + Tailwind search page |
| `caddy/` | Caddy config and the image that serves the built frontend |
| `compose.yaml` | `db` (Postgres + pgvector), `web` (gunicorn), `caddy` |
| `docs/SPEC.md` | Source of truth: requirements, milestones, decision log |

Film data and images are provided by TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.
