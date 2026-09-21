"""What a background job does, without any task-queue machinery, so it is easy to test and reuse."""

from django.conf import settings

from catalog.embed import EmbedStats, embed_pending
from catalog.embedding.factory import get_embedder
from catalog.ingest import FilmItems, IngestStats, ingest_items
from catalog.sources.factory import get_album_source, get_film_source, get_game_source

MEDIA = ("films", "games", "albums")


def resolve_limit(limit: int | None) -> int:
    """The number of new items to ingest: the given limit, else INGEST_LIMIT, else the target."""
    if limit is not None:
        return limit
    return settings.INGEST_LIMIT or settings.CATALOG_TARGET_PER_TYPE


def ingest(media: str, limit: int | None = None) -> IngestStats:
    """Ingest one media type. Raises the same source errors the ingest_* commands turn into
    messages; the caller decides whether to retry."""
    if media == "films":
        source = FilmItems(get_film_source())
    elif media == "games":
        source = get_game_source()
    elif media == "albums":
        source = get_album_source()
    else:
        raise ValueError(f"Unknown media type {media!r}; expected one of {MEDIA}")
    return ingest_items(
        source, limit=resolve_limit(limit), mid_tail_percent=settings.MID_TAIL_PERCENT
    )


def embed(limit: int | None = None) -> EmbedStats:
    """Embed items that still need a vector. Stops cleanly, keeping progress, at a quota limit."""
    return embed_pending(get_embedder(), limit=limit)
