from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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


class FilmSource(Protocol):
    def popular_films(self) -> Iterator[FilmRecord]:
        """Films above the popularity threshold, most popular first. Lazy: fetches on demand."""
        ...

    def mid_tail_films(self) -> Iterator[FilmRecord]:
        """Lesser-known films just below the threshold, so results can surprise."""
        ...
