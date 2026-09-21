from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from catalog.embedding.base import EmbeddingError, EmbedKind
from catalog.models import EMBEDDING_DIMENSIONS
from catalog.sources.albums import AlbumSource
from catalog.sources.base import FilmRecord, ItemRecord, ScoreRecord
from catalog.sources.lastfm import LastFmAlbum, LastFmAlbumInfo
from catalog.sources.musicbrainz import ReleaseGroup
from catalog.sources.wikipedia import WikiIntro

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


# --- the album pipeline's collaborators, as recording fakes -------------------------------------


def mbid(kind: int, n: int) -> str:
    """A well-formed MusicBrainz id. `kind` separates releases (1) from release-groups (2)."""
    return f"{n:08x}-0000-4000-8000-{kind:012x}"


class FakeLastFm:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, int], list[LastFmAlbum]] = {}
        self.infos: dict[str, LastFmAlbumInfo | None] = {}
        self.top_calls: list[tuple[str, int]] = []
        self.info_calls: list[str] = []
        self.error: Exception | None = None

    def top_albums(self, tag: str, page: int) -> list[LastFmAlbum]:
        self.top_calls.append((tag, page))
        return self.pages.get((tag, page), [])

    def album_info(self, release_mbid: str) -> LastFmAlbumInfo | None:
        self.info_calls.append(release_mbid)
        return self.infos.get(release_mbid)


class FakeMusicBrainz:
    def __init__(self) -> None:
        self.groups_of_release: dict[str, str | None] = {}
        self.groups: dict[str, ReleaseGroup | None] = {}
        self.release_calls: list[str] = []
        self.group_calls: list[str] = []
        self.error: Exception | None = None

    def release_group_id(self, release_mbid: str) -> str | None:
        self.release_calls.append(release_mbid)
        if self.error:
            raise self.error
        return self.groups_of_release.get(release_mbid)

    def release_group(self, group_mbid: str) -> ReleaseGroup | None:
        self.group_calls.append(group_mbid)
        return self.groups.get(group_mbid)


class FakeCoverArt:
    def __init__(self) -> None:
        self.without_cover: set[str] = set()
        self.calls: list[str] = []

    def front_cover_url(self, group_mbid: str) -> str | None:
        self.calls.append(group_mbid)
        if group_mbid in self.without_cover:
            return None
        return f"https://coverartarchive.org/release-group/{group_mbid}/front-500"


class FakeWikipedia:
    def __init__(self) -> None:
        self.by_qid: dict[str, WikiIntro] = {}
        self.calls: list[list[str]] = []

    def intros(self, wikidata_ids) -> dict[str, WikiIntro]:
        ids = list(wikidata_ids)
        self.calls.append(ids)
        return {q: self.by_qid[q] for q in ids if q in self.by_qid}


class FakeLedger:
    def __init__(self) -> None:
        self.known: set[str] = set()
        self.groups: set[str] = set()
        self.skipped: dict[str, str] = {}
        self.linked: list[tuple[str, str]] = []

    def is_known(self, release_mbid: str) -> bool:
        return release_mbid in self.known

    def group_item_exists(self, group_mbid: str) -> bool:
        return group_mbid in self.groups

    def link_release(self, group_mbid: str, release_mbid: str) -> None:
        self.linked.append((group_mbid, release_mbid))

    def is_skipped(self, release_mbid: str) -> bool:
        return release_mbid in self.skipped

    def mark_skipped(self, release_mbid: str, reason: str) -> None:
        self.skipped[release_mbid] = reason


class AlbumWorld:
    """A small pretend music universe wired into an AlbumSource, for pipeline tests."""

    def __init__(self, **source_options: object) -> None:
        self.lastfm = FakeLastFm()
        self.musicbrainz = FakeMusicBrainz()
        self.coverart = FakeCoverArt()
        self.wikipedia = FakeWikipedia()
        self.ledger = FakeLedger()
        options: dict[str, object] = {
            "tags": ["rock", "pop"],
            "min_listeners": 1000,
            "mid_tail_min_listeners": 100,
            "batch_size": 20,
            "clock": lambda: NOW,
        }
        options.update(source_options)
        self.source = AlbumSource(
            lastfm=self.lastfm,  # type: ignore[arg-type]
            musicbrainz=self.musicbrainz,  # type: ignore[arg-type]
            coverart=self.coverart,  # type: ignore[arg-type]
            wikipedia=self.wikipedia,  # type: ignore[arg-type]
            ledger=self.ledger,
            **options,  # type: ignore[arg-type]
        )

    def add(
        self,
        n: int,
        *,
        tag: str = "rock",
        page: int = 1,
        listeners: int | None = 5000,
        tags: tuple[str, ...] = ("indie", "night drive"),
        with_mbid: bool = True,
        studio: bool = True,
        group: int | None = None,
        wikidata: bool = True,
        intro: bool = True,
        cover: bool = True,
        year: int | None = 1997,
        release_exists: bool = True,
    ) -> str:
        """Add album n to a Last.fm tag page. Returns its release id."""
        release = mbid(1, n)
        group_id = mbid(2, group if group is not None else n)
        entry = LastFmAlbum(
            name=f"Album {n}",
            artist=f"Artist {n}",
            mbid=release if with_mbid else None,
            url=f"https://www.last.fm/music/Artist+{n}/Album+{n}",
        )
        self.lastfm.pages.setdefault((tag, page), []).append(entry)
        if with_mbid:
            self.lastfm.infos[release] = LastFmAlbumInfo(
                tags=tags,
                listeners=listeners,
                url=f"https://www.last.fm/music/Artist+{n}/Album+{n}",
            )
            self.musicbrainz.groups_of_release[release] = group_id if release_exists else None
            qid = f"Q{n + 1000}" if wikidata else None
            self.musicbrainz.groups[group_id] = ReleaseGroup(
                mbid=group_id,
                title=f"Album {n}",
                artist=f"Artist {n}",
                primary_type="Album",
                secondary_types=() if studio else ("Live",),
                release_year=year,
                wikidata_id=qid,
            )
            if qid and intro:
                self.wikipedia.by_qid[qid] = WikiIntro(
                    wikidata_id=qid,
                    title=f"Album {n}",
                    text=f"Album {n} is an invented studio album.",
                    url=f"https://en.wikipedia.org/wiki/Album_{n}",
                )
            if not cover:
                self.coverart.without_cover.add(group_id)
        return release
