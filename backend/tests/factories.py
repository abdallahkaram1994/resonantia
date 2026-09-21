from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from catalog.embedding.base import EmbeddingError, EmbedKind
from catalog.models import EMBEDDING_DIMENSIONS
from catalog.sources.base import FilmRecord, ItemRecord, ScoreRecord

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def make_record(source_id: int = 1, **overrides: object) -> FilmRecord:
    values: dict[str, object] = {
        "source_id": source_id,
        "title": f"Film {source_id}",
        "release_year": 2001,
        "overview": f"Overview of film {source_id}.",
        "genres": ("Drama",),
        "keywords": ("rain",),
        "cover_url": f"https://image.tmdb.org/t/p/w342/film{source_id}.jpg",
        "original_title": f"Film {source_id}",
        "original_language": "en",
        "runtime": 100,
        "tagline": "",
        "vote_average": 7.0,
        "vote_count": 1500,
        "fetched_at": NOW,
    }
    values.update(overrides)
    return FilmRecord(**values)  # type: ignore[arg-type]


def make_item_record(source_id: str = "1", **overrides: object) -> ItemRecord:
    """A game-shaped record by default; override fields (or media_type and source) as needed."""
    values: dict[str, object] = {
        "media_type": "game",
        "source": "igdb",
        "source_id": source_id,
        "title": f"Game {source_id}",
        "release_year": 2015,
        "summary": f"Summary of game {source_id}.",
        "genres": ("Role-playing (RPG)",),
        "keywords": ("open world",),
        "cover_url": f"https://images.igdb.com/igdb/image/upload/t_cover_big/co{source_id}.jpg",
        "details": {"platforms": ["PC"]},
        "fetched_at": NOW,
        "score": ScoreRecord("igdb", 84.2, 1500),
    }
    values.update(overrides)
    return ItemRecord(**values)  # type: ignore[arg-type]


class FakeItemSource:
    """Yields the given item records lazily and counts how many were actually pulled."""

    def __init__(
        self, popular: Iterable[ItemRecord] = (), mid_tail: Iterable[ItemRecord] = ()
    ) -> None:
        self._popular = list(popular)
        self._mid_tail = list(mid_tail)
        self.popular_pulled = 0
        self.mid_tail_pulled = 0

    def popular(self) -> Iterator[ItemRecord]:
        for record in self._popular:
            self.popular_pulled += 1
            yield record

    def mid_tail(self) -> Iterator[ItemRecord]:
        for record in self._mid_tail:
            self.mid_tail_pulled += 1
            yield record


class FakeFilmSource:
    """Yields the given records lazily and counts how many were actually pulled."""

    def __init__(
        self, popular: Iterable[FilmRecord] = (), mid_tail: Iterable[FilmRecord] = ()
    ) -> None:
        self._popular = list(popular)
        self._mid_tail = list(mid_tail)
        self.popular_pulled = 0
        self.mid_tail_pulled = 0

    def popular_films(self) -> Iterator[FilmRecord]:
        for record in self._popular:
            self.popular_pulled += 1
            yield record

    def mid_tail_films(self) -> Iterator[FilmRecord]:
        for record in self._mid_tail:
            self.mid_tail_pulled += 1
            yield record


class StaticEmbedder:
    """Returns one fixed vector for every text, and records what it was asked to embed."""

    def __init__(self, vector: list[float], model: str = "test-model") -> None:
        self.model = model
        self.dimensions = EMBEDDING_DIMENSIONS
        self._vector = vector
        self.calls: list[tuple[list[str], EmbedKind]] = []

    def embed(self, texts, kind):
        self.calls.append((list(texts), kind))
        return [list(self._vector) for _ in texts]


class FakeEmbedder:
    """Deterministic vectors. Raises `error` when asked for the `fail_on`-th text (1-based)."""

    def __init__(
        self,
        model: str = "test-model",
        fail_on: int | None = None,
        error: EmbeddingError | None = None,
    ) -> None:
        self.model = model
        self.dimensions = EMBEDDING_DIMENSIONS
        self.texts: list[str] = []
        self.kinds: list[EmbedKind] = []
        self._fail_on = fail_on
        self._error = error

    def embed(self, texts, kind):
        vectors = []
        for text in texts:
            if self._fail_on is not None and len(self.texts) + 1 == self._fail_on:
                assert self._error is not None
                raise self._error
            self.texts.append(text)
            self.kinds.append(kind)
            vectors.append([(len(text) % 7 + 1) / 10.0] * self.dimensions)
        return vectors
