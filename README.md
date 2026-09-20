# Resonantia

A vibe-first search across **games, films, and albums**. Describe a feeling ("a rainy night drive") and get matches from all three media types through one shared embedding space, with a detail page and "more like this" for each item.

**Status:** milestone 1 (scaffold). The stack runs and a placeholder page shows a backend health check. Search is not built yet. The plan and the decision log are in [docs/SPEC.md](docs/SPEC.md).

## Prerequisites

- Docker with Compose
- [uv](https://docs.astral.sh/uv/) (Python 3.12 is managed by uv)
- Node 24 and npm

## Quick start

```bash
cp .env.example .env        # then set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up --build
```

Open http://localhost:8080. The page should report the backend, database, and pgvector as healthy. `docker compose down` stops the stack; add `-v` to also delete the database.

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

CI runs the same checks plus a stack smoke test. [CLAUDE.md](CLAUDE.md) has the full command list and project conventions.

## Layout

| Path | What |
|---|---|
| `backend/` | Django + DRF API, `uv` project, tests |
| `frontend/` | React + Vite + TypeScript + Tailwind |
| `caddy/` | Caddy config and the image that serves the built frontend |
| `compose.yaml` | `db` (Postgres + pgvector), `web` (gunicorn), `caddy` |
| `docs/SPEC.md` | Source of truth: requirements, milestones, decision log |
