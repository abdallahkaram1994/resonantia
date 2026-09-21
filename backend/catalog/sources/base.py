from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from catalog.models import MediaType


class SourceError(Exception):
    """Base class. Messages are safe to log: they never contain credentials."""


class SourceUnavailable(SourceError):
    """The source is down, unreachable, or returned something unusable. Try again later."""


class SourceRequestError(SourceError):
    """The source rejected the request or the setup is wrong (for example a bad token)."""


@dataclass(frozen=True)
class FilmRecord:
    source_id: int
    title: str
    release_year: int | None
    overview: str
    genres: tuple[str, ...]
    keywords: tuple[str, ...]
    cover_url: str
    original_title: str
    original_language: str
    runtime: int | None
    tagline: str
    vote_average: float | None
    vote_count: int | None
    fetched_at: datetime

    @property
    def is_embeddable(self) -> bool:
        """Minimum metadata for a film: an overview and at least one genre or keyword."""
        return bool(self.overview) and bool(self.genres or self.keywords)

    def to_item_record(self, source: str) -> "ItemRecord":
        return ItemRecord(
            media_type=MediaType.FILM,
            source=source,
            source_id=str(self.source_id),
            title=self.title,
            release_year=self.release_year,
            summary=self.overview,
            genres=self.genres,
            keywords=self.keywords,
            cover_url=self.cover_url,
            details={
                "original_title": self.original_title,
                "original_language": self.original_language,
                "runtime": self.runtime,
                "tagline": self.tagline,
                "genres": list(self.genres),
                "keywords": list(self.keywords),
            },
            fetched_at=self.fetched_at,
            score=(
                ScoreRecord(source, self.vote_average, self.vote_count)
                if self.vote_average is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ScoreRecord:
    """Display-only. Scores are never embedded and never affect ranking."""

    source: str
    value: float
    vote_count: int | None = None


@dataclass(frozen=True)
class ItemRecord:
    """One catalog item from any source, ready to be stored.

    `source` and `source_id` identify the item at its provider and are how a re-run finds it again.
    `extra_ids` are further ids for the same item (for example a Wikidata id), stored best-effort.
    `field_sources` names the provider of any field that did not come from `source` itself.
    """

    media_type: str
    source: str
    source_id: str
    title: str
    release_year: int | None
    summary: str
    genres: tuple[str, ...]
    keywords: tuple[str, ...]
    cover_url: str
    details: Mapping[str, Any]
    fetched_at: datetime
    byline: str = ""
    keywords_label: str = "Keywords"
    score: ScoreRecord | None = None
    extra_ids: tuple[tuple[str, str], ...] = ()
    field_sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_embeddable(self) -> bool:
        """Minimum metadata (SPEC section 5). Films and games need a summary and at least one
        genre or keyword; albums need tags, and a Wikipedia summary is optional."""
        if self.media_type == MediaType.ALBUM:
            return bool(self.keywords)
        return bool(self.summary) and bool(self.genres or self.keywords)


class ItemSource(Protocol):
    def popular(self) -> Iterator[ItemRecord]:
        """Items above the popularity threshold, most popular first. Lazy: fetches on demand."""
        ...

    def mid_tail(self) -> Iterator[ItemRecord]:
        """Lesser-known items just below the threshold, so results can surprise."""
        ...


class FilmSource(Protocol):
    def popular_films(self) -> Iterator[FilmRecord]:
        """Films above the popularity threshold, most popular first. Lazy: fetches on demand."""
        ...

    def mid_tail_films(self) -> Iterator[FilmRecord]:
        """Lesser-known films just below the threshold, so results can surprise."""
        ...
