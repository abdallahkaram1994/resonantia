from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from django.db import transaction
from django.db.models import Min

from catalog.models import ExternalId, Item, MediaType, Score
from catalog.sources.base import FilmRecord, FilmSource
from catalog.text import build_combined_text

SOURCE = "tmdb"
SOURCED_FIELDS = ("title", "release_year", "cover_url", "summary", "details")

Outcome = Literal["created", "updated", "unchanged"]


@dataclass
class IngestStats:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_not_embeddable: int = 0
    with_keywords: int = 0

    @property
    def ingested(self) -> int:
        return self.created + self.updated + self.unchanged


def upsert_film(record: FilmRecord) -> Outcome:
    """Create or refresh one film. A changed combined text clears its stale embedding."""
    fetched_at = record.fetched_at.astimezone(UTC).isoformat()
    fields = {
        "title": record.title,
        "release_year": record.release_year,
        "cover_url": record.cover_url,
        "summary": record.overview,
        "details": {
            "original_title": record.original_title,
            "original_language": record.original_language,
            "runtime": record.runtime,
            "tagline": record.tagline,
            "genres": list(record.genres),
            "keywords": list(record.keywords),
        },
    }
    combined_text = build_combined_text(
        record.title, record.genres, record.keywords, record.overview
    )
    with transaction.atomic():
        external = (
            ExternalId.objects.select_related("item")
            .filter(source=SOURCE, external_id=str(record.source_id))
            .first()
        )
        item = external.item if external else Item(media_type=MediaType.FILM)
        if external is None:
            outcome: Outcome = "created"
        elif item.combined_text == combined_text and all(
            getattr(item, name) == value for name, value in fields.items()
        ):
            outcome = "unchanged"
        else:
            outcome = "updated"

        for name, value in fields.items():
            setattr(item, name, value)
        item.set_combined_text(combined_text)
        item.provenance = {
            name: {"source": SOURCE, "fetched_at": fetched_at} for name in SOURCED_FIELDS
        }
        item.save()
        if external is None:
            ExternalId.objects.create(item=item, source=SOURCE, external_id=str(record.source_id))

        if record.vote_average is None:
            Score.objects.filter(item=item, source=SOURCE).delete()
        else:
            Score.objects.update_or_create(
                item=item,
                source=SOURCE,
                defaults={
                    "value": record.vote_average,
                    "vote_count": record.vote_count,
                    "fetched_at": record.fetched_at,
                },
            )
    return outcome


def ingest_films(
    source: FilmSource,
    *,
    limit: int,
    mid_tail_percent: int,
    progress: Callable[[IngestStats], None] | None = None,
) -> IngestStats:
    """Ingest up to `limit` embeddable films: popular ones first, then a mid-tail slice.

    Films that fail the minimum-metadata rule are skipped and do not count toward the limit.
    Each film is committed on its own, so an interrupted run keeps its progress.
    """
    mid_target = round(limit * mid_tail_percent / 100)
    stats = IngestStats()
    seen: set[int] = set()
    for stream, target in (
        (source.popular_films(), limit - mid_target),
        (source.mid_tail_films(), mid_target),
    ):
        taken = 0
        while taken < target:
            record = next(stream, None)
            if record is None:
                break
            if record.source_id in seen:
                continue
            seen.add(record.source_id)
            if not record.is_embeddable:
                stats.skipped_not_embeddable += 1
                continue
            outcome = upsert_film(record)
            setattr(stats, outcome, getattr(stats, outcome) + 1)
            if record.keywords:
                stats.with_keywords += 1
            taken += 1
            if progress:
                progress(stats)
    return stats


def oldest_tmdb_fetch() -> datetime | None:
    return Score.objects.filter(source=SOURCE).aggregate(oldest=Min("fetched_at"))["oldest"]


def stale_cache_warning(oldest: datetime | None, max_days: int, now: datetime) -> str | None:
    """TMDB's terms forbid caching its data for more than 6 months, so warn before that."""
    if oldest is None or now - oldest <= timedelta(days=max_days):
        return None
    age_days = (now - oldest).days
    return (
        f"Some TMDB data was fetched {age_days} days ago, past the {max_days}-day refresh window "
        "(TMDB's terms limit caching to 6 months). Re-run ingest_films to refresh it."
    )
