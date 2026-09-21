"""Background jobs, run by the `worker` container (SPEC section 9b).

The full catalog ingest normally runs on the developer's machine; these are for small top-ups.
Jobs are idempotent and resumable: ingest skips what is already stored, and embedding continues
where it stopped. A failing job never affects search, which stays synchronous.
"""

import logging

from procrastinate import RetryStrategy
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from catalog import jobs
from catalog.embedding.base import EmbeddingUnavailable
from catalog.sources.base import SourceUnavailable

logger = logging.getLogger(__name__)

# A transient outage is retried three times, after 8 s, 64 s and about 8.5 min, so the job runs
# four times in all and then fails. Anything that will not fix itself, such as a rejected key,
# fails at once instead of looping.
RETRY = RetryStrategy(
    max_attempts=3,
    exponential_wait=8,
    retry_exceptions={SourceUnavailable, EmbeddingUnavailable},
)


@app.task(queue="ingest", retry=RETRY, queueing_lock="embed_pending")
def embed_pending(limit: int | None = None) -> None:
    stats = jobs.embed(limit)
    if stats.stopped is not None:
        reason = (
            "the daily quota is used up (it resets at midnight Pacific time)"
            if stats.stopped.quota_exhausted
            else "the provider is rate limiting"
        )
        logger.warning(
            "Embedding stopped early after %d items because %s. Progress is kept; run the job "
            "again later.",
            stats.embedded,
            reason,
        )
    else:
        logger.info("Embedded %d items.", stats.embedded)


def _queue_embedding() -> None:
    """Ingested items still need vectors. One queued job is enough, so a duplicate is ignored."""
    try:
        embed_pending.defer()
    except AlreadyEnqueued:
        logger.info("An embedding job is already queued.")


def _ingest(media: str, limit: int | None) -> None:
    stats = jobs.ingest(media, limit)
    logger.info(
        "Ingested %s: %d created, %d updated, %d unchanged, %d skipped.",
        media,
        stats.created,
        stats.updated,
        stats.unchanged,
        stats.skipped_not_embeddable,
    )
    _queue_embedding()


@app.task(queue="ingest", retry=RETRY, queueing_lock="ingest_films")
def ingest_films(limit: int | None = None) -> None:
    _ingest("films", limit)


@app.task(queue="ingest", retry=RETRY, queueing_lock="ingest_games")
def ingest_games(limit: int | None = None) -> None:
    _ingest("games", limit)


# MusicBrainz allows about one request a second per client, so album jobs never overlap.
@app.task(queue="ingest", retry=RETRY, queueing_lock="ingest_albums", lock="musicbrainz")
def ingest_albums(limit: int | None = None) -> None:
    _ingest("albums", limit)
