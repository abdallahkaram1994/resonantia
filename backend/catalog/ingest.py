from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from django.db import transaction
from django.db.models import Min

from catalog.models import ExternalId, Item, Score
from catalog.sources.base import FilmRecord, FilmSource, ItemRecord, ItemSource, TargetAware
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


def _link_extra_ids(item: Item, record: ItemRecord) -> None:
    """Best effort: an id already attached to a different item is left alone, not stolen."""
    for source, external_id in record.extra_ids:
        existing = ExternalId.objects.filter(source=source, external_id=external_id).first()
        if existing is None:
            ExternalId.objects.create(item=item, source=source, external_id=external_id)


def upsert_item(record: ItemRecord) -> Outcome:
    """Create or refresh one item. A changed combined text clears its stale embedding."""
    fetched_at = record.fetched_at.astimezone(UTC).isoformat()
    fields = {
        "title": record.title,
        "release_year": record.release_year,
        "cover_url": record.cover_url,
        "summary": record.summary,
        "details": dict(record.details),
    }
    combined_text = build_combined_text(
        record.title,
        record.genres,
        record.keywords,
        record.summary,
        byline=record.byline,
        keywords_label=record.keywords_label,
    )
    with transaction.atomic():
        external = (
            ExternalId.objects.select_related("item")
            .filter(source=record.source, external_id=record.source_id)
            .first()
        )
        item = external.item if external else Item(media_type=record.media_type)
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
            name: {
                "source": record.field_sources.get(name, record.source),
                "fetched_at": fetched_at,
            }
            for name in SOURCED_FIELDS
        }
        item.save()
        if external is None:
            ExternalId.objects.create(item=item, source=record.source, external_id=record.source_id)
        _link_extra_ids(item, record)

        if record.score is None:
            Score.objects.filter(item=item, source=record.source).delete()
        else:
            Score.objects.update_or_create(
                item=item,
                source=record.score.source,
                defaults={
                    "value": record.score.value,
                    "vote_count": record.score.vote_count,
                    "fetched_at": record.fetched_at,
                },
            )
    return outcome


def ingest_items(
    source: ItemSource,
    *,
    limit: int,
    mid_tail_percent: int,
    progress: Callable[[IngestStats], None] | None = None,
) -> IngestStats:
    """Ingest up to `limit` embeddable items: popular ones first, then a mid-tail slice.

    Items that fail the minimum-metadata rule are skipped and do not count toward the limit.
    Each item is committed on its own, so an interrupted run keeps its progress.
    """
    mid_target = round(limit * mid_tail_percent / 100)
    stats = IngestStats()
    seen: set[tuple[str, str]] = set()
    for open_stream, target in (
        (source.popular, limit - mid_target),
        (source.mid_tail, mid_target),
    ):
        if isinstance(source, TargetAware):
            source.set_target(target)
        stream = open_stream()
        taken = 0
        while taken < target:
            record = next(stream, None)
            if record is None:
                break
            key = (record.source, record.source_id)
            if key in seen:
                continue
            seen.add(key)
            if not record.is_embeddable:
                stats.skipped_not_embeddable += 1
                continue
            outcome = upsert_item(record)
            setattr(stats, outcome, getattr(stats, outcome) + 1)
            if record.keywords:
                stats.with_keywords += 1
            taken += 1
            if progress:
                progress(stats)
    return stats


def upsert_film(record: FilmRecord) -> Outcome:
    return upsert_item(record.to_item_record(SOURCE))


class FilmItems:
    """Presents a film source as a generic item source."""

    def __init__(self, source: FilmSource) -> None:
        self._source = source

    def popular(self) -> Iterator[ItemRecord]:
        return (film.to_item_record(SOURCE) for film in self._source.popular_films())

    def mid_tail(self) -> Iterator[ItemRecord]:
        return (film.to_item_record(SOURCE) for film in self._source.mid_tail_films())


def ingest_films(
    source: FilmSource,
    *,
    limit: int,
    mid_tail_percent: int,
    progress: Callable[[IngestStats], None] | None = None,
) -> IngestStats:
    return ingest_items(
        FilmItems(source), limit=limit, mid_tail_percent=mid_tail_percent, progress=progress
    )


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
