"""The album pipeline: Last.fm finds popular albums, MusicBrainz identifies them, the Cover Art
Archive and Wikipedia add the cover and the summary.

Every step goes by id. An album Last.fm lists without a MusicBrainz id is dropped, never matched
by title, because a wrong match would put the wrong tags on the wrong record.
"""

from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from catalog.ledger import GROUP_SOURCE, RELEASE_SOURCE, Ledger
from catalog.models import MediaType
from catalog.sources.base import ItemRecord
from catalog.sources.coverart import CoverArtArchive
from catalog.sources.lastfm import LastFmAlbum, LastFmAlbumInfo, LastFmClient
from catalog.sources.musicbrainz import MusicBrainzClient, ReleaseGroup
from catalog.sources.wikipedia import WikiIntro, WikipediaClient

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_PAGES = 200  # a safety cap; ingest stops at its limit long before this
HEARTBEAT_EVERY = 25  # Last.fm lookups between progress messages
PREPARE_HEARTBEAT_EVERY = 5  # MusicBrainz identifications between progress messages


def load_lines(path: Path) -> list[str]:
    """Lines of a config list file: no blanks or # comments, and no repeats (ignoring case)."""
    seen: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            seen.setdefault(text.lower(), text)
    return list(seen.values())


@dataclass
class _Candidate:
    release_mbid: str
    album: LastFmAlbum
    info: LastFmAlbumInfo


@dataclass
class _Prepared:
    candidate: _Candidate
    group: ReleaseGroup
    # Other releases of the same album met in this run; they are linked to the item too.
    extra_releases: list[str] = field(default_factory=list)


class AlbumSource:
    def __init__(
        self,
        *,
        lastfm: LastFmClient,
        musicbrainz: MusicBrainzClient,
        coverart: CoverArtArchive,
        wikipedia: WikipediaClient,
        ledger: Ledger,
        tags: Sequence[str],
        min_listeners: int,
        mid_tail_min_listeners: int,
        batch_size: int,
        mid_tail_start_page: int = 1,
        mid_tail_max_scan: int | None = None,
        heartbeat: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._lastfm = lastfm
        self._musicbrainz = musicbrainz
        self._coverart = coverart
        self._wikipedia = wikipedia
        self._ledger = ledger
        self._tags = list(tags)
        self._min_listeners = min_listeners
        self._mid_tail_min_listeners = mid_tail_min_listeners
        self._batch_size = batch_size
        # Popular albums fill the first pages of every tag, and the mid-tail band only appears
        # deeper, so that stream starts further in. Its scan cap stops a search that finds nothing.
        self._mid_tail_start_page = mid_tail_start_page
        self._mid_tail_max_scan = mid_tail_max_scan
        self._heartbeat = heartbeat
        self._clock = clock
        self._prepared_count = 0
        self._want: int | None = None
        # Streams that gave up, with the number of albums they checked.
        self.gave_up: dict[str, int] = {}
        # Why albums were left out, counted once per album across both streams.
        self.drops: Counter[str] = Counter()
        self._counted: set[tuple[str, str]] = set()
        # Both streams walk the same Last.fm pages, so answers are kept and asked for only once.
        self._pages: dict[tuple[str, int], list[LastFmAlbum]] = {}
        self._infos: dict[str, LastFmAlbumInfo | None] = {}
        self._seen_releases: set[str] = set()
        self._prepared_groups: dict[str, _Prepared] = {}

    def __repr__(self) -> str:
        return f"AlbumSource(min_listeners={self._min_listeners})"

    def set_target(self, count: int) -> None:
        """How many albums the next stream is needed for, so a small run does not identify a full
        batch of albums it will never store."""
        self._want = count

    def popular(self) -> Iterator[ItemRecord]:
        return self._stream("popular", lambda listeners: listeners >= self._min_listeners)

    def mid_tail(self) -> Iterator[ItemRecord]:
        return self._stream(
            "mid-tail",
            lambda listeners: self._mid_tail_min_listeners <= listeners < self._min_listeners,
            start_page=self._mid_tail_start_page,
            max_scan=self._mid_tail_max_scan,
        )

    def _say(self, message: str) -> None:
        if self._heartbeat:
            self._heartbeat(message)

    def _drop(self, reason: str, key: str) -> None:
        if (reason, key) not in self._counted:
            self._counted.add((reason, key))
            self.drops[reason] += 1

    def _skip(self, release_mbid: str, reason: str) -> None:
        """A rejection worth remembering, so the next run does not look the album up again."""
        self._ledger.mark_skipped(release_mbid, reason)
        self._drop(reason, release_mbid)

    def _top_albums(self, tag: str, page: int) -> list[LastFmAlbum]:
        if (tag, page) not in self._pages:
            self._pages[(tag, page)] = self._lastfm.top_albums(tag, page)
        return self._pages[(tag, page)]

    def _info(self, release_mbid: str) -> LastFmAlbumInfo | None:
        if release_mbid not in self._infos:
            self._infos[release_mbid] = self._lastfm.album_info(release_mbid)
        return self._infos[release_mbid]

    def _candidates(
        self,
        label: str,
        accept: Callable[[int], bool],
        start_page: int = 1,
        max_scan: int | None = None,
    ) -> Iterator[_Candidate]:
        """Albums in the wanted listener band. Page 1 of every tag comes before page 2 of any, so
        even a small run draws from a spread of genres. Each new album costs one Last.fm lookup
        (for its listener count), so `max_scan` bounds how many a stream may check."""
        scanned = 0
        for page in range(start_page, MAX_PAGES + 1):
            found_any = False
            for tag in self._tags:
                albums = self._top_albums(tag, page)
                found_any = found_any or bool(albums)
                for album in albums:
                    if album.mbid is None:
                        self._drop("no_mbid", f"{album.artist}|{album.name}")
                        continue
                    if album.mbid not in self._infos:
                        if max_scan is not None and scanned >= max_scan:
                            self.gave_up[label] = scanned
                            return
                        scanned += 1
                        if scanned % HEARTBEAT_EVERY == 0:
                            self._say(f"  {label}: checked {scanned} albums on Last.fm...")
                    info = self._info(album.mbid)
                    if info is None:
                        self._drop("lastfm_not_found", album.mbid)
                    elif not info.tags:
                        self._drop("no_tags", album.mbid)
                    elif info.listeners is None:
                        self._drop("no_listener_count", album.mbid)
                    elif info.listeners < self._mid_tail_min_listeners:
                        self._drop("below_threshold", album.mbid)
                    elif accept(info.listeners):
                        yield _Candidate(album.mbid, album, info)
            if not found_any:
                return

    def _prepare(self, candidate: _Candidate) -> _Prepared | None:
        """Identify the album at MusicBrainz and keep only studio albums not seen before."""
        release = candidate.release_mbid
        if release in self._seen_releases:
            return None
        self._seen_releases.add(release)
        if self._ledger.is_known(release):
            self._drop("already_ingested", release)
            return None
        if self._ledger.is_skipped(release):
            self._drop("previously_skipped", release)
            return None

        group_id = self._musicbrainz.release_group_id(release)
        if group_id is None:
            self._skip(release, "no_release_group")
            return None
        if group_id in self._prepared_groups:
            self._prepared_groups[group_id].extra_releases.append(release)
            self._drop("duplicate", release)
            return None
        if self._ledger.group_item_exists(group_id):
            self._ledger.link_release(group_id, release)
            self._drop("duplicate", release)
            return None

        group = self._musicbrainz.release_group(group_id)
        if group is None:
            self._skip(release, "not_found")
            return None
        if not group.is_studio_album:
            self._skip(release, "not_studio_album")
            return None
        prepared = _Prepared(candidate, group)
        self._prepared_groups[group_id] = prepared
        self._prepared_count += 1
        if self._prepared_count % PREPARE_HEARTBEAT_EVERY == 0:
            self._say(f"  {self._prepared_count} albums identified at MusicBrainz so far...")
        return prepared

    def _stream(
        self,
        label: str,
        accept: Callable[[int], bool],
        start_page: int = 1,
        max_scan: int | None = None,
    ) -> Iterator[ItemRecord]:
        want, self._want = self._want, None  # a target applies to one stream only
        yielded = 0

        def batch_limit() -> int:
            if want is None:
                return self._batch_size
            return max(1, min(self._batch_size, want - yielded))

        pending: list[_Prepared] = []
        for candidate in self._candidates(label, accept, start_page, max_scan):
            prepared = self._prepare(candidate)
            if prepared is None:
                continue
            pending.append(prepared)
            if len(pending) >= batch_limit():
                for record in self._finish(pending):
                    yielded += 1
                    yield record
                pending = []
        for record in self._finish(pending):
            yield record

    def _finish(self, batch: list[_Prepared]) -> Iterator[ItemRecord]:
        """Covers one by one, then one batched Wikipedia lookup for the whole batch."""
        if batch:
            self._say(f"  finishing {len(batch)} albums (covers and Wikipedia summaries)...")
        covers = {p.group.mbid: self._coverart.front_cover_url(p.group.mbid) for p in batch}
        intros = self._wikipedia.intros(p.group.wikidata_id for p in batch if p.group.wikidata_id)
        for prepared in batch:
            wikidata_id = prepared.group.wikidata_id
            yield self._record(
                prepared,
                covers[prepared.group.mbid] or "",
                intros.get(wikidata_id) if wikidata_id else None,
            )

    def _record(self, prepared: _Prepared, cover_url: str, intro: WikiIntro | None) -> ItemRecord:
        group, candidate = prepared.group, prepared.candidate
        extra_ids = [(RELEASE_SOURCE, candidate.release_mbid)]
        extra_ids += [(RELEASE_SOURCE, release) for release in prepared.extra_releases]
        if group.wikidata_id:
            extra_ids.append(("wikidata", group.wikidata_id))
        field_sources = {"details": "musicbrainz+lastfm"}
        if cover_url:
            field_sources["cover_url"] = "coverartarchive"
        if intro:
            field_sources["summary"] = "wikipedia"
        return ItemRecord(
            media_type=MediaType.ALBUM,
            source=GROUP_SOURCE,
            source_id=group.mbid,
            title=group.title,
            release_year=group.release_year,
            summary=intro.text if intro else "",
            genres=(),
            keywords=candidate.info.tags,
            keywords_label="Tags",
            byline=group.artist or candidate.album.artist,
            cover_url=cover_url,
            details={
                "artist": group.artist or candidate.album.artist,
                "primary_type": group.primary_type,
                "release_group_mbid": group.mbid,
                "release_mbid": candidate.release_mbid,
                "tags": list(candidate.info.tags),
                "lastfm": {
                    "listeners": candidate.info.listeners,
                    "url": candidate.info.url or candidate.album.url,
                },
                "wikipedia": {"title": intro.title, "url": intro.url} if intro else None,
            },
            fetched_at=self._clock(),
            extra_ids=tuple(extra_ids),
            field_sources=field_sources,
        )
