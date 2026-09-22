# Resonantia — Project Spec

**Status:** requirements settled; milestones 1 (scaffold), 2 (films end to end), 3 (games, albums and the worker) and 4 (search behavior: filters, layout, item detail, "more like this", full-text fallback) built.
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
| TMDB | Films: metadata, posters, overview, ratings (`vote_average`, `vote_count`), streaming availability by region | TMDB logo and non-endorsement notice required. **Non-commercial use only.** Data must not be cached longer than 6 months. Terms section 1.C also restrict use "in connection with... a machine learning or AI based Application"; that risk is accepted (see the decision log). Availability is JustWatch-powered. |
| IGDB (via Twitch OAuth) | Games: metadata, covers, summary, ratings, store links | Free for non-commercial use under the Twitch Developer Services Agreement (see the decision log). Token by client credentials; about 4 requests/second. Field names verified against the live API in M3 (section 5). Store links and attribution wording are still to do (M8). |
| MusicBrainz | Albums: canonical release groups, artists, year, Wikidata links | ~1 request/second (503 when exceeded). Descriptive User-Agent with a contact required. Core data is CC0; its tags and genres are CC BY-NC-SA, so we do not use them. |
| Last.fm | Album discovery (popular albums per genre tag), tags | Free API key, **non-commercial use only**. Popularity, not quality. Its terms give a "temporary" licence limited to a small portion of the data, and ask for credit with the "powered by AudioScrobbler" button (decision log). |
| Cover Art Archive | Album covers | Found by release-group id. A HEAD request tells us whether art exists (307 to archive.org, or 404). We store the stable `coverartarchive.org` URL, never the redirect target. |
| Wikipedia (MediaWiki API) + Wikidata | Album summaries | CC BY-SA: show "Source: Wikipedia" link and license note. Descriptive User-Agent required. Wikidata gives the English article title; the intro text is fetched in batches. |
| OMDb | Display-only Rotten Tomatoes/Metacritic scores | ~1,000 requests/day free: fetch lazily on detail-page view and cache. |
| Gemini API | LLM parsing/rerank/explain and embeddings | Free tier, no card. Embeddings are verified (section 6). Free-tier content may be used by Google and read by human reviewers (decision log). **(verify)** LLM models and limits in M5. |
| Groq or Mistral | Fallback LLM provider | Free tier. **(verify)** |

**Dropped:** OpenCritic (free tier too limited), HowLongToBeat, direct RT/Metacritic, Discogs, Last.fm album wiki as a summary source.

**Images:** store URLs/IDs only and hotlink from source CDNs. Nothing is stored or proxied by us. That includes the TMDB logo in the footer. Attribution for every source goes in the footer.

---

## 5. Catalog

- ~**2,000 items per media type** (~6,000 total).
- Selection: popularity threshold (TMDB vote count, IGDB rating count, Last.fm listeners) plus a small **mid-tail slice** so results can surprise.
- **Minimum metadata to be embeddable:**
  - Film: overview and at least one genre or keyword
  - Game: summary and at least one genre or theme
  - Album: tags present (a Wikipedia summary is *not* required)
- **Album ingestion:** Last.fm top albums across ~50–100 genre tags → resolve to a MusicBrainz release group (Last.fm often returns the MBID) → Cover Art Archive for art → Wikipedia via the Wikidata link on the MusicBrainz record. **Albums that cannot be matched cleanly are dropped; never guess by title search.** The exact rules are under "Album resolution" below.
- Ingest is a config-driven, resumable, throttled background job. `INGEST_LIMIT=N` per type for small sample runs. It runs as management commands (`ingest_films`, `ingest_games`, `ingest_albums`, then `embed_items`) on the developer's machine, and the same code runs as worker jobs (`enqueue_job`, section 9b) for small top-ups.
- **Film selection** (all thresholds in config): "popular" means at least `FILM_MIN_VOTE_COUNT` TMDB votes (default 1,000), most-voted first. The mid-tail slice (`MID_TAIL_PERCENT`, default 10%, shared by every media type) comes from the band starting at `FILM_MID_TAIL_MIN_VOTE_COUNT` (default 200) up to the popular threshold, ordered by popularity. Vote counts only select films; they never affect ranking.
- **Game selection** (all thresholds in config): **main games only**, meaning IGDB `game_type = 0` with no `version_parent`, which leaves out DLC, expansions, bundles, editions, remakes and remasters. (The older `category` field is deprecated and returns nothing.) "Popular" means at least `GAME_MIN_RATING_COUNT` ratings (default 75, which about 2,100 games meet), most-rated first. The mid-tail band runs from `GAME_MID_TAIL_MIN_RATING_COUNT` (default 25) up to that threshold. One query returns 100 games with genres, themes, keywords and the cover id, so there are no per-game detail calls. IGDB keywords are noisy user tags (some games have 200), so only `GAME_MAX_KEYWORDS` (default 10) go into the text. The IGDB rating is stored as a display-only `Score` and never embedded.
- **Album selection** (all thresholds in config): "popular" means at least `ALBUM_MIN_LISTENERS` Last.fm listeners (default 50,000) on `album.getInfo`. The mid-tail band runs from `ALBUM_MID_TAIL_MIN_LISTENERS` (default 10,000) up to that. Popular albums fill the first pages of every tag and the mid-tail band only appears deep in the lists, so that search starts at `ALBUM_MID_TAIL_START_PAGE` (default 20) and gives up, with a hint, after `ALBUM_MID_TAIL_MAX_SCAN` albums (default 1,000). The tags come from `catalog/data/lastfm_tags.txt` (70 genre tags); `lastfm_tag_blocklist.txt` removes listener tags such as "seen live" and "favourites", and an album's own artist and title, before the rest (at most `ALBUM_MAX_TAGS`, default 10) go into the text. Listener counts only select albums; they never affect ranking.
- **Album resolution (never by title).** Every step goes by id:
  1. Last.fm `tag.getTopAlbums` gives name, artist and a release MBID. **An album without an MBID is dropped.**
  2. `album.getInfo` by MBID gives tags and listeners. No usable tags, no listener count, or too few listeners: dropped.
  3. MusicBrainz `release/{mbid}` resolves the release to its **release group**; the release-group lookup gives the title, artist credit, `first-release-date` and the Wikidata relation. Only **primary type Album with no secondary type** is kept, so live albums, compilations, EPs, singles and soundtracks are dropped.
  4. Several releases of one album (several tags, reissues) map to one item through the release-group id. Every release id is stored as an `ExternalId`.
  5. The Cover Art Archive answers a HEAD for the release group. An album with no cover is kept, with no cover.
  6. The Wikidata id gives the English article title, and the Wikipedia intro is fetched in batches (up to 50 ids and 20 titles per request). No article means no summary, which is allowed.
  7. `first-release-date` may be `1997`, `1997-05`, a full date or empty; each maps to an integer year or null.
- **Drop reasons.** The ingest commands count every album left out and print the reasons: `no_mbid`, `lastfm_not_found`, `no_tags`, `no_listener_count`, `below_threshold`, `already_ingested`, `previously_skipped`, `duplicate` (another release of an album already handled), `no_release_group`, `not_found` and `not_studio_album`. Releases MusicBrainz rejected are stored in `SkippedRecord` so a re-run does not repeat those lookups; `ingest_albums --retry-skipped` looks at them again.
- **Album cost:** roughly 3 to 4 seconds per album (one Last.fm call, two MusicBrainz calls at one per second, and the Cover Art Archive and Wikipedia calls), so 2,000 albums take about two hours. Ingest is resumable, so it can be run in pieces.
- **Embedding budget:** one embedding request per item, and the free tier allows about 1,000 requests a day, so embedding ~6,000 items takes about six days of quota, and a model change costs the same again. `embed_items` saves each vector as it arrives and stops cleanly when the quota runs out.
- **TMDB refresh:** TMDB data must not be cached longer than 6 months. Every TMDB-sourced field carries `fetched_at`, and `ingest_films` warns when catalog data is older than `TMDB_MAX_CACHE_DAYS` (default 150). A restored dump counts, so check its age after a redeploy.
- **Full ingest runs on the developer's machine.** The finished catalog (embeddings included) is dumped with `pg_dump` and restored on the VPS. Keep a copy of the dump for future redeploys.

---

## 6. Data model (conceptual)

- **Item:** canonical record. `media_type`, `title`, `release_year` (nullable int), `cover_url`, `summary`, `combined_text`, `content_hash`, `embedding` (vector), `embedding_model`, `embedding_dim`, timestamps. Type-specific fields live in a `details` JSON column. The database refuses a vector stored without its model and dimension.
- **ExternalId:** maps an Item to source IDs (`source`, `external_id`). This is the entity-resolution layer. An album has one for its MusicBrainz release group (`musicbrainz`), one for every release seen (`musicbrainz-release`) and one for its Wikidata item.
- **SkippedRecord:** `source`, `external_id`, `reason`, `checked_at`; unique per source and id. Remembers rejected source records (for example a live album) so a re-run does not repeat the lookups.
- **Provenance:** every sourced field records `source` and `fetched_at`, kept as a JSON map on the item.
- **Score (display-only):** `item`, `source`, `value`, `vote_count`, `fetched_at`; unique per item and source (a source with several scores, like OMDb, needs distinct source names).
- **Availability (films):** `item`, `region`, `service`, `kind`, `fetched_at`. Store all regions from the TMDB response.
- **Cache tables:** query embeddings, parsed intents, full results, rate-limit counters (Postgres, UNLOGGED or DB-backed).

**Combined text per item:** title + genres/tags + summary (or Wikipedia text when available). One text, one vector. **Ratings are never embedded.** Films and games use a `Genres:` line and a `Keywords:` line. Albums add `By: <artist>` under the title and call their list `Tags:`. The film text is locked by golden-hash tests, because changing it would force re-embedding the whole film catalog.

**Embeddings:** Gemini **`gemini-embedding-2`** reduced to **768 dimensions** (verified September 2026). It replaced the earlier default `gemini-embedding-001`, which is legacy with a shutdown announced for May 2028. It normalizes truncated vectors itself and accepts 8,192 input tokens. It has no task-type parameter, so retrieval instructions go in the text: documents are sent as `title: none | text: <combined text>` (the combined text already starts with the title) and queries as `task: search result | query: <text>`. **Each text is its own request**, because a list of texts in one request comes back as a single aggregated vector. Store the model and dimension per row, and only ever compare vectors of the same model and dimension (enforced in SQL). Changing the model means re-embedding the catalog. `content_hash` (sha256 of the combined text) skips unchanged items on re-runs: a changed text clears the stored vector so the item is embedded again.

**Retrieval:** an exact cosine scan with no ANN index. At ~6,000 items it is fast, and it keeps "filters in SQL before ranking" exact (a filtered approximate index can return too few rows). Revisit if the catalog grows. Cosine scores sit in a narrow band (about 0.55 to 0.6 for a query against a film, and 0.73 on average between two films), so use them for ordering only and never show them as a percentage.

---

## 7. Search behavior

### 7.1 Pipeline

1. **Normalize** the query: lowercase, trim, collapse whitespace. Hard cap **200 characters** (config), checked after normalizing: a longer query is rejected with a 400, never truncated.
2. **Cache lookup** on the full-result key (normalized query + filters + embedding model + prompt version).
3. **Parse** with the LLM into `{vibe_text, media_type_hint}`, validated against a strict schema. If parsing fails, use the raw query as `vibe_text` with no hint.
4. **Embed** `vibe_text` (cached by normalized text).
5. **Retrieve** per enabled type with pgvector similarity, applying filters in SQL *before* ranking. Candidate pool ~50 per type.
6. **Lay out and return** (see 7.3). Return ~10 per type when grouped, ~15 when blended, with an optional "show more". Results are never reranked by an LLM; layout order is pgvector similarity (7.3's blend/standout scoring) only.

At most one LLM call per uncached search (parse). A second, small LLM call happens only when a visitor opens an item's detail page reached from a search: see "Explanations" below, and the decision log ("Match explanations").

**Built in M4:** normalize → query-embedding cache lookup (step 4's cache, not step 2's full-result cache, which is M6) → embed → retrieve per type with filters in SQL, `SEARCH_CANDIDATES_PER_TYPE` (default 50) per type → lay out (7.3) → return. A query too long is a 400; an embedding failure falls back to full-text search (7.5) instead of failing.

**Built in M5:** step 3 (LLM query parsing) is live — a failure is silent, falling back to the raw query with no hint, exactly as M4's placeholder behaved. Grouped layout is now reachable from real requests. A rerank step was designed above but not built; see "Explanations".

**Explanations (M5, replaces the rerank+explain step above):** no LLM call happens during search itself, and results are never reranked. When a visitor opens an item's detail page reached from a search (`GET /api/items/<id>/?q=...`), one small LLM call (`explain_match`) explains why that specific item matches, grounded only in its own stored metadata (never other candidates). It runs at most once per item actually opened, not once per search. Any failure (misconfigured key, rate limit, provider outage, malformed response) just omits the explanation; the page never breaks. See the decision log for why this replaced the in-search rerank+explain design.

### 7.2 Filters

- **Media type toggles:** hard constraints applied in SQL. Toggling a filter re-runs only SQL, using cached intent and embedding. **Built in M4:** films and games are on by default; albums start off, but are fully searchable by switching the toggle on (see the decision log — embedding hubness among albums).
- **Era:** decade chips (80s, 90s, 00s…) in the UI, sent to the API as `eras=1980-1989,1990-1999` (chips OR'd, at most 10 ranges, each within 1800–2200). Stored as integer `release_year`.
  - No era filter active: keep items with null year.
  - Era filter active: drop items with null year.
  - Albums and games/films use their own release date.
- **Architecture:** a filter registry. Each filter declares `applies_to` (a set of media types). The query builder generates one predicate per enabled type and ORs them, so a type-scoped filter can never touch another type's rows. Types with no active filters pass through. No type-scoped filters ship in v1, but adding one must be a single class.
- **Type-scoped filter semantics:** narrows only its own type; other types stay. Removing a type is the media type toggle's job.
- **Precedence:** UI toggles win. If the query names a type that is toggled off, show a short notice and let the toggle win.
- LLM-parsed values are validated against the same schema.

### 7.3 Layout (hybrid)

- One type enabled → single ranked list.
- Multiple types enabled and the query names a type → **grouped**, named type first, `SEARCH_GROUP_LIMIT` (default 10) per group. A type with no matches still appears, empty, so the page can say so.
- Multiple types enabled, no type named → **blended** list, `SEARCH_RESULT_LIMIT` (default 15) items. Each type with matches is guaranteed `SEARCH_BLEND_MIN_SLOTS` (default 2) slots so it is never crowded out entirely; the rest go to the highest-standing hits regardless of type (see "Blending: standout score" below).
- Per-type filters apply inside each type's candidate pool *before* scores are normalized and merged.

**Blending: standout score, not min-max.** The original idea — scale each type's pool from its own weakest to its own best hit (0 to 1) — was tried and rejected after testing against the real, embedded catalog: every type's own best hit always scales to 1, even a barely-relevant one, so a type that plainly did not fit the query still won equal footing in the blend. The catalog is also dense enough (many items sit at a broadly similar distance from most queries) that within-pool scaling barely differentiates a genuinely strong match from a mediocre one.

The built approach scores each hit by how many standard deviations above its **own type's average similarity to this query** it sits (a z-score), computed against the whole type — every item of that type, not just the retrieved candidates — so filters never change a hit's standing. This needs one extra aggregate query per enabled type (a mean and a population standard deviation over that type's embedded rows), cheap at the catalog's size. Verified on the real catalog: for "epic fantasy adventure" it correctly ranked Skyrim and two Lord of the Rings films above weaker matches from every type, instead of an unrelated album's single strong hit crowding out equally strong films purely because it happened to be that album pool's best.

### 7.4 Ranking

**Vibe similarity only, for all media types.** Ratings do not affect ranking (consistency across types, discovery feel). Albums have no usable free quality signal, so a boost would rank types differently.

- A per-type **quality weight** exists in config, default `0`, so a boost can be enabled later if results skew toward low-quality items. If ever enabled: percentile within media type, Bayesian-averaged for low vote counts, missing data neutral, applied only to already-retrieved candidates.

### 7.5 Fallbacks

| Failure | Behavior |
|---|---|
| LLM unavailable or invalid output | Embedding-only search; no explanations; raw query as vibe |
| Primary LLM rate-limited | Fall back to secondary provider |
| Embedding API unavailable or budget circuit breaker tripped | Serve cached results, else **Postgres full-text search** (`tsvector` on title, tags, description). Show a short notice. |

**Built in M4.** Any embedding failure (provider down, rate-limited, or misconfigured) now falls back to Postgres full-text search rather than failing the request: the response is a normal `200` with `mode: "text"` and a notice explaining the degradation, not the `503` that section 9 describes for "search failures" (that policy still holds for anything that fails *both* ways, which cannot currently happen — there is no other failure mode modeled yet). "Serve cached results" today only means the query-embedding cache (a hit there needs no provider call at all and stays in vibe mode); the full result cache that would let a *previously failed* query still serve a cached ranked list is M6.

Full-text matching reduces the query to plain `[a-z0-9]` words (never handed to Postgres' own query syntax) and OR's them, so a partial phrase match still counts, then ranks with plain `ts_rank`, **not** `ts_rank_cd`. Cover-density ranking was tried first, since it is usually the better choice, but tested directly against Postgres it rewards a document that repeats one matched word over one that matches several different words for an OR query — a document with "rain" four times outranked one with "rain" and "night" each once. Plain `ts_rank` gets this the right way round. A GIN index on `combined_text` backs the match itself (confirmed via `EXPLAIN` on the real catalog: a bitmap index scan, not a sequential scan). The same filters and the same layout code apply in text mode; standing for the blend is scaled within each type's own matched pool rather than against the whole catalog like vibe mode, since a full-text pool is mostly exact non-matches elsewhere and the cheaper approach is not misleading there the way it was for vibe search.

---

## 8. Pages and UX

Style reference: Letterboxd (poster-grid, clean, dense metadata). Flow: land → type a prompt → see results → open an item → see similar items.

- **Landing:** a single prompt box, plus pre-warmed example queries (served from cache, so the first click costs nothing) — the prompt box is built; pre-warming is M6 (needs the result cache).
- **Results:** cover grid per the layout rules, media type toggles, decade chips. URL holds state: `/search?q=…&types=…&eras=…` (`types`/`eras` are left out of the URL when they equal the defaults, for a clean address). A cover is fitted inside its type's box, never cropped to fill it — a source image's real proportions do not reliably match its type's usual shape (an IGDB game cover especially can be almost any aspect ratio), so cropping was zooming into the middle of some of them.
- **Detail:** real route `/item/<id>` (not a modal), built in M4. Shows cover, summary, metadata, and scores.
  - Films: TMDB score. OMDb scores and streaming availability are not built yet (M8/M9).
  - Games: IGDB score. Store links are not built yet (M8); IGDB is not even asked for that data until then.
  - Albums: no score. Wikipedia summary with attribution ("Source: *title* on Wikipedia", linked, plus a CC BY-SA 4.0 link), or "No summary available for this album."
  - **Match explanation (M5):** when the visitor arrived from a search (the page's own URL carries `?q=…`), one short sentence explaining why this item matches, grounded only in its own stored metadata. See section 7.1 ("Explanations") and the decision log.
  - **"More like this":** one pgvector query using the item's stored vector, excluding itself, grouped by media type, `ITEM_SIMILAR_LIMIT` (default 10) total across every type. **No external calls.** Unlike blended search, this has no per-type minimum reservation — one type can fill the whole list — since it is a single global ranking, not a merge of separately filtered pools. A weak, tonally-mismatched item occasionally appears this way (a franchise sequel's neighbors can include an unrelated film that happens to share several genre/keyword words); see the decision log for what was checked and deliberately deferred.
- **Region:** auto-detect from Cloudflare's country header (trusted only when the request comes from Cloudflare ranges), plus a small picker that overrides it, stored client-side. Fall back to US when there is no data. Not built yet (M9).
- **Footer:** attribution and non-endorsement notices for every source. Built in M4 for TMDB, IGDB, Last.fm ("powered by AudioScrobbler"), MusicBrainz and the Cover Art Archive; the Wikipedia licence note is per-item on the album detail page instead, where the text it credits actually appears.

---

## 9. Abuse control, rate limiting, caching

**Threat model:** the LLM and embedding tiers are free, so abuse cannot cost money. The real risk is bots exhausting the daily quota so real visitors get nothing. Per-IP limits alone do not stop a distributed botnet, so a global cap is the backstop. Worst case, everything is beaten and search degrades for a day; no bill.

### Rate limits (all values in config; tune to actual free-tier quotas)
- **Cache-miss searches per IP:** strict (starting point ~3/min and ~20/day).
- **All search requests per IP:** looser.
- **Global daily circuit breaker:** stop LLM/embedding calls at ~70% of the free quota.
- **Provider-side per-minute limiter:** never trip the provider's own limits.
- **Embedding quota (observed free tier, September 2026):** 100 requests/minute, 30K tokens/minute, and **1,000 requests/day**, resetting at midnight Pacific time. Every uncached search spends one request embedding its query, and ingest draws on the same budget. At the 70% breaker that is about 700 searches a day before caching, which is why the query-embedding cache matters.
- Return `429` with `Retry-After`; the UI explains politely.

### Other controls
- Query length cap; LLM output validated against schema; the LLM sees only the query and stored item metadata and has **no tools**.
- Search failures return one generic 503 (with `Retry-After` when the provider gave a delay). Provider error details are logged, never returned, and **query text is never logged**. **Built in M4:** an embedding failure specifically no longer reaches this path — it falls back to full-text search (7.5) and returns a normal 200 instead, so this 503 is reserved for a failure the fallback cannot cover (none exists yet).
- Until this milestone (M6) is built, the search endpoint has no rate limits and must not be exposed publicly.
- Signed session cookie issued on page load and required by the API.
- Cloudflare Turnstile challenge after a few searches or on suspicious behavior **(verify** current terms; use Cloudflare's dummy keys locally).
- CORS locked to our origin; ingest/admin endpoints not publicly routable; `robots.txt` disallows the API.
- **Real client IP:** read `CF-Connecting-IP` only when the request originates from Cloudflare's published ranges. Get this wrong and either everyone shares one IP or attackers spoof theirs.
- Tiered limits protect legitimate users behind shared IPs.

### Caching layers (Postgres-backed, no Redis)
1. Query embedding cache (normalized text). **Built in M4**, pulled forward from M6: a `QueryEmbedding` row keyed by a hash of the normalized text plus the embedding model and dimension, so toggling a filter on an already-searched query costs no provider quota. The query text itself is never stored, only its hash, consistent with "query text is never logged" above. Pruning old rows is still M6.
2. Parsed-intent cache
3. Full result cache (ranked IDs + explanations), keyed with embedding model and prompt version so changes invalidate automatically; long TTL since the catalog rarely changes
4. Detail pages and "more like this": HTTP cache headers, no external calls
5. OMDb scores stored in the DB with `fetched_at`
6. **Stampede protection:** concurrent identical misses share one upstream call
7. Pre-warmed example queries

---

## 9b. Background worker

**Choice: Procrastinate**, a Postgres-backed task queue with a Django integration, retries, periodic tasks, and task locks. It runs as the `worker` container, built from the same image as `web` with a different command, and needs only the Postgres we already run.

**Why not Celery:** Celery needs a separate broker (usually Redis or RabbitMQ), which adds a service and RAM on a 2 GB server. Also considered: django-q2, and Django's newer built-in tasks API with a database backend. Procrastinate was picked because retries, cron-style periodic tasks, and locks come built in with no extra infrastructure. Keep task code behind thin wrappers so swapping later is feasible. Version 3.9.0 with its Django integration was verified working in M3. The project has said it is looking for more maintainers.

### What runs on the worker

| Task | Trigger | Notes |
|---|---|---|
| Source ingest (per source and media type) | Manual / management command | Resumable and throttled. The full ingest normally runs on the developer's machine; the VPS worker only does small top-ups. |
| Embedding batch | After ingest, or when `content_hash` changes | Respects the daily embedding quota and continues the next day if exhausted. |
| Refresh streaming availability | Periodic (TTL of days) | TMDB watch providers. |
| Refresh scores | Periodic (TTL of weeks) | TMDB and IGDB. OMDb stays lazy, not bulk. |
| Cache and counter pruning | Periodic (hourly or daily) | Expired result, embedding, and intent cache rows; rate-limit counters. |
| Pre-warm example queries | Periodic (daily) and after deploy | Uses the circuit-breaker budget; skipped when budget is low. |

### Built in M3

- **Jobs** (`backend/catalog/tasks.py`, all on the `ingest` queue): `ingest_films`, `ingest_games`, `ingest_albums` and `embed_pending`, each taking an optional `limit`. What a job does lives in `catalog/jobs.py`, shared with the management commands, so the queue stays a thin wrapper. An ingest job queues an `embed_pending` job when it finishes.
- **Queue locks:** each job has its own queueing lock, so the same job cannot wait in the queue twice (a second request is refused and the command says so). `ingest_albums` also holds the `musicbrainz` lock, so two album jobs never run at once.
- **Retries:** a temporary outage (`SourceUnavailable`, `EmbeddingUnavailable`) is retried three times, after about 8 seconds, 64 seconds and 8.5 minutes, so a job runs four times at most. A rejected key, bad configuration or a bug fails at once. Hitting the embedding quota is not a failure: `embed_pending` logs a warning, keeps its progress and returns.
- **Running it:** `docker compose up` starts the `worker` service, which needs `web` to be healthy first (so the migrations, including the queue's own tables, are applied) and runs `manage.py procrastinate worker --queues ingest,maintenance --concurrency $WORKER_CONCURRENCY` (default 2). Its healthcheck is `procrastinate healthchecks`. Unlike `web`, it receives the whole `.env`, because ingest jobs call TMDB, IGDB and Last.fm. Queue a job with `manage.py enqueue_job <job> [--limit N]` and follow it with `docker compose logs -f worker`. The `maintenance` queue exists but has no jobs until M6.
- **CI:** the stack job waits for the worker's healthcheck, queues `embed_pending` and waits for it to succeed.

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
- `.env` (gitignored) holds keys; `.env.example` is committed with every variable listed and placeholders. Keep each variable on one line and defined once: Docker Compose uses the **last** duplicate but `uv run --env-file` uses the **first**. Use letters and digits only in `POSTGRES_PASSWORD`, since the two tools parse `$`, `#`, quotes and backslashes differently. The database keeps the password it was first created with, so after changing it run `docker compose down -v`.
- Tests use **fixtures**: no keys, no network. CI runs the same way. Third-party content is not committed: TMDB fixtures are invented films in TMDB's response shape, because TMDB's terms limit caching and redistribution and the repository is public. Error bodies may be real recordings when they contain no third-party content.
- Manual checks use a small sample ingest (`INGEST_LIMIT=50`) before the full run.
- Only production-only behavior (Cloudflare real-IP, HTTPS, origin firewall) is verified at deploy time, with unit tests using simulated headers beforehand.

### Keys and inputs the developer supplies

| When | What |
|---|---|
| M2 | TMDB **read-access token** (not the short API key), Gemini API key, and your AI Studio embedding limits (RPM, TPM, RPD) |
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
- **Open from M4, to measure here rather than judge from single examples:** album vibe-search quality (its combined text is mostly encyclopedic Wikipedia biography — release dates, labels, chart certifications — with little mood-descriptive language, unlike a film or game's synopsis and keyword list), and whether "more like this" needs a content-rating signal (a franchise sequel's neighbors can include a tonally unrelated item that shares several genre/keyword words; MPAA/ESRB data is confirmed fetchable from TMDB and IGDB at no extra request cost and would need to be embedded as text, not used as a filter, to keep ranking vibe-similarity-only — but re-embeds the whole film and game catalog, a real one-time quota cost).
- **Also found in M4, and partly acted on:** embedding hubness among albums — a small number of albums sit disproportionately close to many unrelated queries (confirmed on the real catalog: one album was the nearest album match for 20% of a 500-film sample, regardless of what any of those films were about). This is a distinct, more fundamental problem than the text-quality one above — better album text would not necessarily fix it, since hubness is a known effect in high-dimensional nearest-neighbor search generally. The symptom (albums crowding default results with a repetitive handful of matches) was mitigated immediately by leaving albums out of the default search (decision log); the underlying cause is not fixed and would need a proper correction (each item scored against its own typical similarity level, not just its type's pool for one query), which belongs here, evaluated against the golden set.

---

## 13. Milestones

Each milestone ends with tests passing, docs updated, and a stop for human review. One small PR per slice.

1. **Scaffold:** Compose stack (`db` with Postgres+pgvector, `web`, `caddy`; the `worker` container arrives in M3), a minimal front-end scaffold (Vite + React + TypeScript + Tailwind with one placeholder page that calls a backend health endpoint; no product UI), CI covering backend and front-end (lint, typecheck, tests, build), `CLAUDE.md`, `.env.example`. *Accept:* `docker compose up` starts the stack; the pgvector extension is enabled; Caddy serves the built front-end at `/` and proxies `/api` to Django; the placeholder page shows the health check result; CI passes.
2. **Films end to end:** data model with provenance, TMDB adapter, combined-text builder, `Embedder` interface, basic search endpoint, bare-bones page. *Accept:* a real query returns relevant films locally.
3. **Games and albums:** IGDB adapter; Last.fm, MusicBrainz, Cover Art Archive, Wikipedia/Wikidata; entity resolution; Procrastinate worker container with resumable ingest and embedding tasks. *Accept:* sample ingest of all three types.
4. **Search behavior:** filters via the registry, hybrid layout, "more like this", Postgres full-text fallback. *Accept:* toggles and era chips narrow results without crashing; a type-scoped filter never touches another type's rows; the fallback still returns something useful when embedding is forced to fail. Built with a working search UI, poster grid and detail page too, pulled forward from M8 since M4 needed a browser to verify filters and layout against; the query-embedding cache was pulled forward from M6 for the same reason (toggling a filter must not cost quota to be worth having). See the decision log for what changed from the original design after testing against the real catalog.
5. **LLM layer:** provider interface, query parsing wired into search, schema validation, forced-failure fallbacks, lazy per-item match explanations on the detail page (see the decision log for why this replaced the originally planned in-search rerank+explain step).
6. **Protection:** rate limits, caches, circuit breaker, session cookie, Turnstile, Cloudflare header handling; periodic worker tasks (cache and counter pruning, availability/score refresh, pre-warming).
7. **Evaluation:** golden-set harness and CI regression check. Also the right place to revisit the two quality questions logged as open in M4: whether albums need a different text strategy, and whether "more like this" needs a content-rating signal — see the decision log.
8. **Frontend polish:** landing page pre-warming, region picker, remaining polish. The poster grid, detail page and attribution footer arrived in M4 instead (see above).
9. **Deploy:** VPS, Cloudflare, origin lockdown, auto-deploy, backups, restore from dump.
10. **README:** screenshots, screen recording, attributions, this decision log.

Start with films only (M2) because it exposes problems with the data model, embedding text, and search while changes are cheap.

---

## 14. To verify before or during the build

- LLM free-tier limits and fallback provider terms (M5). *Verified in M2:* Gemini embedding model, dimensions and free-tier limits; TMDB attribution wording and image URLs.
- OMDb daily quota. *Verified in M3 against the live IGDB API:* the rating and count fields (`total_rating`, `total_rating_count`), that `game_type` replaces the deprecated `category`, and the cover `image_id`.
- **Terms and AI use.** Checked in M3: Last.fm (non-commercial only, "temporary" licence, no AI clause found), MusicBrainz (core data is CC0) and Wikipedia (CC BY-SA, attribution needed). **Still open:** the text of the Twitch Developer Services Agreement, which governs IGDB, could not be retrieved, so its rules on attribution, redistribution and AI use are unconfirmed (secondary sources: it bans re-distributing API data, no AI clause found). Also open: OMDb's terms, and how Last.fm's "temporary" licence applies to a stored catalog.
- **Attribution to build in M4/M8:** the Last.fm "powered by AudioScrobbler" credit, "Source: Wikipedia" with the licence, and IGDB's required wording. The IGDB and Cover Art Archive image hosts also need to be allowed wherever the frontend restricts image sources.
- **Before M9:** the Gemini free-tier clause that bars services likely accessed by under-18s
- A real Gemini 429 response body: daily-quota detection follows the standard google.rpc format but has only been tested against synthetic fixtures
- Turnstile terms; Cloudflare free-plan rule limits; Cloudflare Registrar availability and price for the chosen name
- RackNerd datacenter options, renewal terms, and taxes at checkout
- Claude Code usage limits on the current plan
- Procrastinate's periodic-task setup (M6)
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
| Embedding model | `gemini-embedding-2`, 768 dims, one text per request | The current recommended model (001 is legacy, shutdown May 2028); it normalizes truncated vectors; a list of texts in one request is aggregated into a single vector |
| TMDB and AI use | Accepted the risk of using TMDB data in an ML/AI application, for non-commercial use only | TMDB's terms (section 1.C) restrict this and TMDB has not answered community questions about non-commercial use. The key could be revoked. Keep the logo, the notice and the refresh rule, and re-evaluate if TMDB objects |
| TMDB data age | Refresh within 6 months; `ingest_films` warns after 150 days | TMDB's terms prohibit caching longer than 6 months; a restored dump counts |
| Free-tier data use | Accept Gemini's free-tier terms, with a visible notice on the search page | The only zero-cost option. Google may use and human-review submitted text, so visitors are told not to enter personal information. Open risk: the terms also bar services likely accessed by under-18s; revisit before deploy |
| Retrieval | Exact cosine scan, no ANN index | ~6,000 items scan fast, and a filtered approximate index can return too few rows; revisit if the catalog grows |
| Query length | Over 200 characters is rejected with a 400, not truncated | Truncating would change the query's meaning |
| Test fixtures | Invented third-party records in the provider's response shape | TMDB's terms limit caching and redistribution, and the repository is public |
| Embedding budget | Resumable, quota-aware embedding; about 1,000 texts a day | The free tier allows 1,000 requests a day, so the full catalog takes about six days |
| IGDB terms | Proceed with IGDB for games, for non-commercial use, accepting the Twitch Developer Services Agreement when registering the app | It is the only free official games source. The agreement text could not be retrieved, so it has not been checked for attribution or AI-use rules; the developer reads it at registration and reports any conflict. If IGDB objects, games can be swapped or dropped, since each source sits behind an adapter |
| Last.fm terms | Use Last.fm for album discovery and tags, non-commercial only | Its terms grant a "temporary" licence limited to a small portion of its data (a 100 MB cap; the catalog needs about 2 MB) and ask for credit with the "powered by AudioScrobbler" button, which ships with the attribution footer. No AI clause found. Risk accepted; if Last.fm objects, albums need another tag source |
| Album scope | Studio albums only (MusicBrainz primary type Album, no secondary type) | Live albums, compilations, EPs and singles would fill results with duplicates of the same music |
| Game scope | Main games only (`game_type = 0`, no `version_parent`) | Editions, DLC, remakes and bundles would fill results with duplicates |
| Album resolution | By id only. An album Last.fm lists without a MusicBrainz id is dropped, never matched by title | A wrong title match puts the wrong tags on the wrong record, and a dropped album costs nothing. Every drop is counted by reason and printed |
| Skipped records | Rejected releases are remembered in `SkippedRecord`, re-checked only with `--retry-skipped` | Each rejection costs MusicBrainz calls at one per second, and a re-run would repeat them |
| Mid-tail thresholds | Games 75 ratings (popular) and 25 (mid-tail floor); albums 50,000 and 10,000 listeners; mid-tail search starts at Last.fm page 20 | Set from live probes in M3: about 2,100 main games have 75 or more ratings, and page 1 of a Last.fm tag has a median near 1,000,000 listeners, so the band below 50,000 only appears deep in the list. Revisit with the full catalog |
| Worker retries | Three retries with backoff (8 s, 64 s, 8.5 min) for temporary outages only | A brief outage should not lose a job, but a rejected key or a bug will not fix itself and should fail at once |
| Worker keys | The `worker` service gets the whole `.env`; `web` keeps a short list | Ingest jobs call TMDB, IGDB and Last.fm. Web serves visitors and needs only the embedding key |
| Worker scope in M3 | Jobs are ingest and embedding only, queued by `enqueue_job`. Periodic jobs come in M6 | The full ingest runs on the developer's machine; the VPS worker is for small top-ups |
| Blending score | Standout (z-score against the whole type's average similarity for this query), not min-max scaling within the retrieved pool | Tested against the real catalog: min-max always scales a pool's own best hit to 1 even when it is a weak match, so a barely-relevant type could win equal footing over a strongly-matching one. Standout needs one extra aggregate query per type but correctly favored genuinely strong matches in a live check |
| Query embedding cache | Pulled forward from M6 into M4, keyed by a hash of the normalized text plus model and dimension; the query text itself is never stored | A filter toggle re-runs the search (section 7.2), and without this every toggle would spend embedding quota on an identical query. Verified live: three searches, one spelling variant, one provider request |
| Embedding-failure response | A 200 with `mode: "text"` and a notice, not the blanket 503 section 9 originally described for "search failures" | The full-text fallback (7.5) makes an embedding outage a degraded-but-successful search, not a failed request; 503 is kept for a failure the fallback itself cannot cover |
| Full-text ranking | Plain `ts_rank`, not `ts_rank_cd` (cover density) | Tested directly against Postgres: for the OR-combined query the fallback builds, cover density rewards repeating one matched word over matching several different ones (a document with "rain" four times outranked one with "rain" and "night" each once). Plain `ts_rank` ranks that the right way round |
| Full-text standing | Scaled within each type's own matched pool (the approach rejected for vibe search), not against the whole catalog | A full-text pool is mostly exact non-matches elsewhere, unlike a dense vibe-similarity pool, so the cheaper within-pool scaling is not misleading here and needs no extra aggregate query |
| "More like this" size | `ITEM_SIMILAR_LIMIT` default 10, no per-type minimum reservation | Matches `SEARCH_GROUP_LIMIT`'s existing convention. It is one global ranking (SPEC section 8), not a merge of separately filtered per-type pools, so blended search's fairness reservation does not apply; lowering the count alone does not reliably filter out a tonally mismatched item, since the similarity drop-off near the cutoff is usually gradual, not a clean break |
| Frontend routing | A small hand-rolled router (`pushState`/`popstate`, one hook, one `Link` component), not a routing library | The app has exactly two page shapes (search and item detail); the existing `?q=` URL state already used this pattern, so extending it was smaller than adding a dependency for two routes |
| Cover fit | `object-contain` (letterboxed), not `object-cover` (cropped to fill) | A source image's real proportions do not reliably match its type's usual box, especially an IGDB game cover; cropping was zooming into the middle of a mismatched image and losing part of it |
| Cover box shapes | Film 2:3, game 3:4, album square — three shapes, not two | Read the real files: TMDB posters (`w342`) are exactly 342x513 (2:3); IGDB covers (`t_cover_big`) are exactly 264x352 (3:4), visibly stubbier; Cover Art Archive is 500x500. Games sharing the film box left visible gray letterboxing on every game cover, in the grid and in "more like this" alike |
| Detail page cover sizing | `items-start` on the cover/metadata row, overriding flexbox's default stretch | A long summary was stretching the sibling flex item, and flexbox's cross-axis stretch overrides a box's own `aspect-ratio`-derived height, not the other way around — the cover grew into a tall gray rectangle around a small, centered image. `aspect-ratio` plus a responsive `max-w-xs` already gives a consistent shape at every viewport width without needing a fixed pixel size |
| Content-rating signal for "more like this" | Checked feasible (TMDB certifications and IGDB age ratings are both fetchable in the same request the ingest already makes, confirmed live), not built | Real cost: changes every already-ingested film and game's combined text, forcing a full re-embed (a real one-time quota cost). Belongs in M7 with the album question, measured against the golden set rather than tuned against one example |
| Default search types | Films and games; albums start switched off but stay fully searchable with `types=album` | Discovered live: a handful of albums are disproportionate nearest-neighbor "hubs" in the shared embedding space, one of them the nearest album match for 20% of a 500-film sample regardless of what those films were about, crowding default results with a repetitive few. A quick, reversible mitigation; the underlying cause (hubness, distinct from the album text-quality question above) is not fixed and belongs in M7 |
| Match explanations | A lazy, per-item `explain_match` call on the detail page (`?q=…`), not the in-search rerank+explain call section 7.1 originally described. No reranking is built | Rerank+explain would cost one guaranteed extra LLM call on *every* uncached search, win or lose, even for the results a visitor never opens; the lazy version costs nothing unless someone actually clicks into an item, and grounding stays just as strict (only that item's own stored text). Revisit if a golden-set evaluation (M7) shows plain similarity order needs reranking |