# Resonantia — Project Spec

**Status:** requirements settled; milestone 1 (scaffold) built.
**Purpose:** portfolio project demonstrating agentic development with Claude. Live for roughly one year while job hunting, then redeployable from the repo plus a database dump.

Items marked **(default)** were proposed as sensible defaults and not explicitly debated. Items marked **(verify)** rely on third-party facts that must be checked against current provider docs before building on them.

---

## 1. Concept

Resonantia is a vibe-first search across **games, films, and albums**. A visitor types a feeling ("moody synth-heavy game", "a rainy night drive"), optionally names a media type, and gets matching items from all three media types. Clicking a result opens a detail page with a "more like this" section.

The differentiator is cross-media mood matching in one shared embedding space. It is retrieval, not collaborative filtering, so it needs no user history and works from day one.

### Non-goals (v1)
- User accounts, saved lists, ratings by users, or any personal data
- Platform, streaming-service, or region *filters* (region only affects displayed streaming availability)
- Republishing review text; scraping; unofficial APIs (HowLongToBeat, direct Rotten Tomatoes/Metacritic)
- Running any ML model on our own server
- Paid services of any kind; Redis; user-generated content

---

## 2. Constraints

| Constraint | Detail |
|---|---|
| Budget | **≤ $60 USD per year total.** VPS $35.99/yr + optional .com ≈ $10.46/yr. Taxes/VAT may add to both. Everything else must be $0. |
| APIs | Official and free only. Non-commercial use. |
| AI billing | No billing account attached to the Gemini (or any AI) project, so overage charges are impossible; quota exhaustion just throttles. |
| Runtime | 2 GB RAM VPS. No local model. |
| Anonymity | No login, no cookies beyond the signed session cookie used for abuse control. |

---

## 3. Stack

- **Backend:** Python 3.12+, Django, Django REST Framework (default), `uv`, `ruff`, `pytest`
- **Database:** Postgres with `pgvector`
- **Background jobs:** **Procrastinate**, a Postgres-backed task queue (see section 9b). Not Celery, no Redis.
- **Frontend:** React, Vite, TypeScript, Tailwind (default), built to static files served by Caddy
- **Runtime:** Docker Compose (`db`, `web` under gunicorn, `worker`, `caddy`)
- **CI/CD:** GitHub Actions, GitHub Container Registry, SSH deploy
- **Repo:** public on GitHub (keeps CI/registry free; doubles as the portfolio)

---

## 4. Data sources

| Source | Used for | Notes |
|---|---|---|
| TMDB | Films: metadata, posters, overview, ratings (`vote_average`, `vote_count`), streaming availability by region | Attribution and non-endorsement notice required. Availability is JustWatch-powered. |
| IGDB (via Twitch OAuth) | Games: metadata, covers, summary, ratings, store links | Free. Verify exact rating/count field names. |
| MusicBrainz | Albums: canonical release groups, artists, year, Wikidata links | ~1 request/second. Descriptive User-Agent required. |
| Last.fm | Album discovery (popular albums per genre tag), tags | Free API key. Popularity, not quality. |
| Cover Art Archive | Album covers | Linked from MusicBrainz. |
| Wikipedia (MediaWiki API) + Wikidata | Album summaries | CC BY-SA: show "Source: Wikipedia" link and license note. Descriptive User-Agent required. |
| OMDb | Display-only Rotten Tomatoes/Metacritic scores | ~1,000 requests/day free: fetch lazily on detail-page view and cache. |
| Gemini API | LLM parsing/rerank/explain and embeddings | Free tier, no card. **(verify)** current models and limits. |
| Groq or Mistral | Fallback LLM provider | Free tier. **(verify)** |

**Dropped:** OpenCritic (free tier too limited), HowLongToBeat, direct RT/Metacritic, Discogs, Last.fm album wiki as a summary source.

**Images:** store URLs/IDs only and hotlink from source CDNs. Nothing is stored or proxied by us. Attribution for every source goes in the footer.

---

## 5. Catalog

- ~**2,000 items per media type** (~6,000 total).
- Selection: popularity threshold (TMDB vote count, IGDB rating count, Last.fm listeners) plus a small **mid-tail slice** so results can surprise.
- **Minimum metadata to be embeddable:**
  - Film: overview and at least one genre or keyword
  - Game: summary and at least one genre or theme
  - Album: tags present (a Wikipedia summary is *not* required)
- **Album ingestion:** Last.fm top albums across ~50–100 genre tags → resolve to a MusicBrainz release group (Last.fm often returns the MBID) → Cover Art Archive for art → Wikipedia via the Wikidata link on the MusicBrainz record. **Albums that cannot be matched cleanly are dropped; never guess by title search.**
- Ingest is a config-driven, resumable, throttled background job. `INGEST_LIMIT=N` per type for small sample runs.
- **Full ingest runs on the developer's machine.** The finished catalog (embeddings included) is dumped with `pg_dump` and restored on the VPS. Keep a copy of the dump for future redeploys.

---

## 6. Data model (conceptual)

- **Item:** canonical record. `media_type`, `title`, `release_year` (nullable int), `cover_url`, `summary`, `combined_text`, `content_hash`, `embedding` (vector), `embedding_model`, `embedding_dim`, timestamps. Type-specific fields in typed columns or JSON.
- **ExternalId:** maps an Item to source IDs (`source`, `external_id`). This is the entity-resolution layer.
- **Provenance:** every sourced field records `source` and `fetched_at`.
- **Score (display-only):** `item`, `source`, `value`, `vote_count`, `fetched_at`.
- **Availability (films):** `item`, `region`, `service`, `kind`, `fetched_at`. Store all regions from the TMDB response.
- **Cache tables:** query embeddings, parsed intents, full results, rate-limit counters (Postgres, UNLOGGED or DB-backed).

**Combined text per item:** title + genres/tags + summary (or Wikipedia text when available). One text, one vector. **Ratings are never embedded.**

**Embeddings:** Gemini `gemini-embedding-001` reduced to **768 dimensions** (default; **verify** the current model and free limits). Store the model and dimension per row. Changing the model means re-embedding the catalog. Use `content_hash` to skip unchanged items on re-runs.

---

## 7. Search behavior

### 7.1 Pipeline

1. **Normalize** the query: lowercase, trim, collapse whitespace. Hard cap **200 characters**.
2. **Cache lookup** on the full-result key (normalized query + filters + embedding model + prompt version).
3. **Parse** with the LLM into `{vibe_text, media_type_hint}`, validated against a strict schema. If parsing fails, use the raw query as `vibe_text` with no hint.
4. **Embed** `vibe_text` (cached by normalized text).
5. **Retrieve** per enabled type with pgvector similarity, applying filters in SQL *before* ranking. Candidate pool ~50 per type.
6. **Rerank and explain** in one LLM call over the top candidates. Explanations are grounded only in stored metadata. If this call fails, return similarity order with no explanations.
7. **Lay out and return** (see 7.3). Return ~10 per type when grouped, ~15 when blended, with an optional "show more".

Two LLM calls maximum per uncached search: parse, then rerank+explain.

### 7.2 Filters

- **Media type toggles** (all on by default): hard constraints applied in SQL. Toggling a filter re-runs only SQL, using cached intent and embedding.
- **Era:** decade chips (80s, 90s, 00s…) in the UI, sent to the API as year ranges `era: [[1980,1989],[1990,1999]]` (chips OR'd). Stored as integer `release_year`.
  - No era filter active: keep items with null year.
  - Era filter active: drop items with null year.
  - Albums and games/films use their own release date.
- **Architecture:** a filter registry. Each filter declares `applies_to` (a set of media types). The query builder generates one predicate per enabled type and ORs them, so a type-scoped filter can never touch another type's rows. Types with no active filters pass through. No type-scoped filters ship in v1, but adding one must be a single class.
- **Type-scoped filter semantics:** narrows only its own type; other types stay. Removing a type is the media type toggle's job.
- **Precedence:** UI toggles win. If the query names a type that is toggled off, show a short notice and let the toggle win.
- LLM-parsed values are validated against the same schema.

### 7.3 Layout (hybrid)

- One type enabled → single ranked list.
- Multiple types enabled and the query names a type → **grouped**, named type first.
- Multiple types enabled, no type named → **blended** list. Normalize scores per type or reserve a minimum share of slots per enabled type so no type dominates.
- Per-type filters apply inside each type's candidate pool *before* scores are normalized and merged.

### 7.4 Ranking

**Vibe similarity only, for all media types.** Ratings do not affect ranking (consistency across types, discovery feel). Albums have no usable free quality signal, so a boost would rank types differently.

- A per-type **quality weight** exists in config, default `0`, so a boost can be enabled later if results skew toward low-quality items. If ever enabled: percentile within media type, Bayesian-averaged for low vote counts, missing data neutral, applied only to already-retrieved candidates.

### 7.5 Fallbacks

| Failure | Behavior |
|---|---|
| LLM unavailable or invalid output | Embedding-only search; no explanations; raw query as vibe |
| Primary LLM rate-limited | Fall back to secondary provider |
| Embedding API unavailable or budget circuit breaker tripped | Serve cached results, else **Postgres full-text search** (`tsvector` on title, tags, description). Show a short notice. |

---

## 8. Pages and UX

Style reference: Letterboxd (poster-grid, clean, dense metadata). Flow: land → type a prompt → see results → open an item → see similar items.

- **Landing:** a single prompt box, plus pre-warmed example queries (served from cache, so the first click costs nothing).
- **Results:** cover grid per the layout rules, media type toggles, decade chips. URL holds state: `/search?q=…&types=…&eras=…`.
- **Detail:** real route `/item/<id>` (not a modal). Shows cover, summary, metadata, scores, and availability.
  - Films: TMDB score, lazily fetched OMDb scores, streaming availability for the visitor's region.
  - Games: IGDB score, store links (Steam, GOG, Epic, etc.).
  - Albums: no score. Wikipedia summary with attribution, or "No summary available for this album."
  - **"More like this":** one pgvector query using the item's stored vector, excluding itself, grouped by media type. **No external calls.**
- **Region:** auto-detect from Cloudflare's country header (trusted only when the request comes from Cloudflare ranges), plus a small picker that overrides it, stored client-side. Fall back to US when there is no data.
- **Footer:** attribution and non-endorsement notices for every source, Wikipedia license note.

---

## 9. Abuse control, rate limiting, caching

**Threat model:** the LLM and embedding tiers are free, so abuse cannot cost money. The real risk is bots exhausting the daily quota so real visitors get nothing. Per-IP limits alone do not stop a distributed botnet, so a global cap is the backstop. Worst case, everything is beaten and search degrades for a day; no bill.

### Rate limits (all values in config; tune to actual free-tier quotas)
- **Cache-miss searches per IP:** strict (starting point ~3/min and ~20/day).
- **All search requests per IP:** looser.
- **Global daily circuit breaker:** stop LLM/embedding calls at ~70% of the free quota.
- **Provider-side per-minute limiter:** never trip the provider's own limits.
- Return `429` with `Retry-After`; the UI explains politely.

### Other controls
- Query length cap; LLM output validated against schema; the LLM sees only the query and stored item metadata and has **no tools**.
- Signed session cookie issued on page load and required by the API.
- Cloudflare Turnstile challenge after a few searches or on suspicious behavior **(verify** current terms; use Cloudflare's dummy keys locally).
- CORS locked to our origin; ingest/admin endpoints not publicly routable; `robots.txt` disallows the API.
- **Real client IP:** read `CF-Connecting-IP` only when the request originates from Cloudflare's published ranges. Get this wrong and either everyone shares one IP or attackers spoof theirs.
- Tiered limits protect legitimate users behind shared IPs.

### Caching layers (Postgres-backed, no Redis)
1. Query embedding cache (normalized text)
2. Parsed-intent cache
3. Full result cache (ranked IDs + explanations), keyed with embedding model and prompt version so changes invalidate automatically; long TTL since the catalog rarely changes
4. Detail pages and "more like this": HTTP cache headers, no external calls
5. OMDb scores stored in the DB with `fetched_at`
6. **Stampede protection:** concurrent identical misses share one upstream call
7. Pre-warmed example queries

---

## 9b. Background worker

**Choice: Procrastinate**, a Postgres-backed task queue with a Django integration, retries, periodic tasks, and task locks. It runs as the `worker` container, built from the same image as `web` with a different command, and needs only the Postgres we already run.

**Why not Celery:** Celery needs a separate broker (usually Redis or RabbitMQ), which adds a service and RAM on a 2 GB server. Also considered: django-q2, and Django's newer built-in tasks API with a database backend. Procrastinate was picked because retries, cron-style periodic tasks, and locks come built in with no extra infrastructure. Keep task code behind thin wrappers so swapping later is feasible. **(verify)** the current version and Django integration docs; the project has said it is looking for more maintainers.

### What runs on the worker

| Task | Trigger | Notes |
|---|---|---|
| Source ingest (per source and media type) | Manual / management command | Resumable and throttled. The full ingest normally runs on the developer's machine; the VPS worker only does small top-ups. |
| Embedding batch | After ingest, or when `content_hash` changes | Respects the daily embedding quota and continues the next day if exhausted. |
| Refresh streaming availability | Periodic (TTL of days) | TMDB watch providers. |
| Refresh scores | Periodic (TTL of weeks) | TMDB and IGDB. OMDb stays lazy, not bulk. |
| Cache and counter pruning | Periodic (hourly or daily) | Expired result, embedding, and intent cache rows; rate-limit counters. |
| Pre-warm example queries | Periodic (daily) and after deploy | Uses the circuit-breaker budget; skipped when budget is low. |

**Not queued:** the search request path stays synchronous. The OMDb lookup on a detail page runs in-request with a short timeout and is cached; if it fails, the page renders without those scores.

### Rules
- Tasks are idempotent and retry with backoff. A failing task never affects search serving.
- Separate queues (e.g. `ingest`, `maintenance`). MusicBrainz work uses a lock or single-concurrency queue to honor ~1 request/second.
- Low worker concurrency to stay inside the RAM budget.
- Job status and manual triggers go through management commands. No public admin endpoints.
- Tasks that call Gemini share the same global circuit breaker as search (section 9).

---

## 10. Deployment

- **Host:** RackNerd 2 GB KVM VPS, $35.99/year (2 vCPU, 35 GB SSD, 1 IPv4). Confirm datacenter location and terms at checkout. Not needed beyond one year; redeploy from repo + dump.
- **Domain:** working name **Resonantia**. Register via Cloudflare Registrar (.com ≈ $10.46/yr) if available, else a variant. Turn off auto-renew if not keeping it.
- **Cloudflare in front:** proxied DNS, SSL mode **Full (strict)** with an origin certificate, Turnstile, free-plan bot/rate rules **(verify** current free-plan limits).
- **Origin lockdown:** firewall ports 80/443 to Cloudflare's IP ranges only, so bots cannot bypass the edge by hitting the raw IP.
- **Auto-deploy:** GitHub Actions on push to `main`: build image → push to GHCR → SSH → `docker compose pull && docker compose up -d` → migrate.
- **Backups:** nightly `pg_dump` copied to the developer's machine. No paid snapshots. The catalog can also be rebuilt by re-running ingest.
- **After the year:** keep a README with screenshots and a short screen recording so the project stays showable when the live site is gone.

---

## 11. Local development

- Same Docker Compose file as production, plus the Vite dev server. Run Claude Code on the host (macOS), not inside a container.
- `.env` (gitignored) holds keys; `.env.example` is committed with every variable listed and placeholders.
- Tests use **recorded fixtures**: no keys, no network. CI runs the same way.
- Manual checks use a small sample ingest (`INGEST_LIMIT=50`) before the full run.
- Only production-only behavior (Cloudflare real-IP, HTTPS, origin firewall) is verified at deploy time, with unit tests using simulated headers beforehand.

### Keys and inputs the developer supplies

| When | What |
|---|---|
| M2 | TMDB API key, Gemini API key |
| M3 | Twitch app client ID/secret (IGDB), Last.fm API key, contact email for MusicBrainz/Wikipedia User-Agent |
| Display scores | OMDb API key |
| M5 | Fallback LLM key (Groq or Mistral) |
| M6 | Turnstile site/secret keys |
| M9 | Domain, VPS IP, SSH key, GitHub Actions secrets |

---

## 12. Evaluation

Testing only; nothing here runs in production or adds cost.

- **Golden set:** ~30 hand-written queries: vibe-only, type-specified, decade-filtered, and edge cases (very short, nonsense, prompt-injection attempts). The developer writes a few expected items (and clear non-matches) per query.
- **Automated checks (no LLM cost):** toggles and era filters respected; type-scoped filters never affect other types; layout rules hold; fallbacks work when the LLM or embedding call is forced to fail.
- **Quality metric:** recall of expected items in the top 10, tracked over time, run in CI against cached embeddings.
- README shows before/after numbers for changes like prompt tweaks or ranking weights.

---

## 13. Milestones

Each milestone ends with tests passing, docs updated, and a stop for human review. One small PR per slice.

1. **Scaffold:** Compose stack (`db` with Postgres+pgvector, `web`, `caddy`; the `worker` container arrives in M3), a minimal front-end scaffold (Vite + React + TypeScript + Tailwind with one placeholder page that calls a backend health endpoint; no product UI), CI covering backend and front-end (lint, typecheck, tests, build), `CLAUDE.md`, `.env.example`. *Accept:* `docker compose up` starts the stack; the pgvector extension is enabled; Caddy serves the built front-end at `/` and proxies `/api` to Django; the placeholder page shows the health check result; CI passes.
2. **Films end to end:** data model with provenance, TMDB adapter, combined-text builder, `Embedder` interface, basic search endpoint, bare-bones page. *Accept:* a real query returns relevant films locally.
3. **Games and albums:** IGDB adapter; Last.fm, MusicBrainz, Cover Art Archive, Wikipedia/Wikidata; entity resolution; Procrastinate worker container with resumable ingest and embedding tasks. *Accept:* sample ingest of all three types.
4. **Search behavior:** filters via the registry, hybrid layout, "more like this", Postgres full-text fallback.
5. **LLM layer:** provider interface (Gemini + fallback), parse and rerank/explain, schema validation, forced-failure fallbacks.
6. **Protection:** rate limits, caches, circuit breaker, session cookie, Turnstile, Cloudflare header handling; periodic worker tasks (cache and counter pruning, availability/score refresh, pre-warming).
7. **Evaluation:** golden-set harness and CI regression check.
8. **Frontend polish:** landing, poster grid, detail page, region picker, attribution footer.
9. **Deploy:** VPS, Cloudflare, origin lockdown, auto-deploy, backups, restore from dump.
10. **README:** screenshots, screen recording, attributions, this decision log.

Start with films only (M2) because it exposes problems with the data model, embedding text, and search while changes are cheap.

---

## 14. To verify before or during the build

- Gemini embedding model name, dimensions, and current free-tier limits; LLM free-tier limits; fallback provider terms
- IGDB rating and count field names; TMDB attribution wording; OMDb daily quota
- Turnstile terms; Cloudflare free-plan rule limits; Cloudflare Registrar availability and price for the chosen name
- RackNerd datacenter options, renewal terms, and taxes at checkout
- Claude Code usage limits on the current plan
- Procrastinate's current version, Django integration docs, and periodic-task setup
- Name availability (domain, GitHub, trademark)

---

## 15. Decision log

| Decision | Choice | Reason |
|---|---|---|
| Idea | Cross-media vibe search (games, films, albums) | Familiar domains; strong data modeling and AI story |
| Primary experience | Search-first; "more like this" as secondary | More flexible and demoable |
| Sources | Official free APIs only | Budget and ToS safety |
| Album summaries | Wikipedia only; otherwise a "no summary" message | No official review APIs; avoids scraping and copyright |
| Embedding space | One shared space across types | Enables cross-media matching |
| Layout | Hybrid grouped/blended, single list for one type | Reliable when type named, impressive when not |
| Filters v1 | Media type toggles + decade chips | Employers will not care about platform/streaming |
| Type-scoped filters | Narrow only their own type | Simple semantics; toggles remove types |
| Ranking | Similarity only; ratings display-only; weight config default 0 | Consistency across types; discovery feel |
| Runtime LLM | Free tier (Gemini primary, fallback provider) | Zero runtime cost; Claude used only for building |
| Embeddings | Hosted API (Gemini, 768-dim) | No model on the server; cheaper VPS |
| Fallback | Postgres full-text search | Works without any external call |
| Accounts | None in v1 | Smaller scope; no personal data |
| Hosting | Single RackNerd 2 GB VPS + Docker Compose | Cheapest way to get workers and one bill |
| Task queue | Procrastinate (Postgres-backed), not Celery | Celery needs a broker (extra service and RAM); Procrastinate needs only Postgres |
| Edge | Cloudflare domain + proxy + Turnstile | Bot control and hidden origin |
| Region | Auto-detect + picker | Correct availability at no extra cost |
| Evaluation | ~30-query golden set, recall@10 | Repeatable quality signal |
| Name | Resonantia | Latin root of "resonance" (echo); domain TBD |
| Migrations | `web` runs `migrate` on every start, then gunicorn | `docker compose up` must yield a working database, and a redeploy migrates with no extra step. Safe with one `web` instance; revisit if that changes |
| Local DB access | Compose publishes `db` on `127.0.0.1` only | Host tools (pytest, psql) need a route to the database; loopback is not reachable from other machines |
| Versions | Django 5.2 LTS, Postgres 17 (`pgvector/pgvector:pg17`), Python 3.12, Node 24, TypeScript 6.0.x | LTS support runs past the one-year lifespan; TypeScript stays below 6.1 until `typescript-eslint` supports 7 |