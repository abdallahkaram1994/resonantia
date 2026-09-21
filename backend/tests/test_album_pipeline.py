"""The album pipeline with the real clients wired together over scripted HTTP, and the ledger that
lets a second run skip the expensive lookups."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import IntegrityError, transaction

from catalog.ingest import ingest_items
from catalog.ledger import DbLedger
from catalog.models import ExternalId, Item, SkippedRecord
from catalog.ratelimit import Throttle
from catalog.sources.albums import AlbumSource
from catalog.sources.coverart import CoverArtArchive
from catalog.sources.lastfm import LastFmClient
from catalog.sources.musicbrainz import MusicBrainzClient
from catalog.sources.wikipedia import WikipediaClient
from tests.factories import make_item_record, mbid
from tests.helpers import FakeClock, ScriptedTransport

pytestmark = pytest.mark.django_db

AGENT = "Resonantia/0.1 (test@example.com)"


# --- DbLedger -------------------------------------------------------------------------------


def stored_album(group: str, release: str | None = None) -> Item:
    from catalog.ingest import upsert_item

    extra = (("musicbrainz-release", release),) if release else ()
    upsert_item(make_item_record(group, media_type="album", source="musicbrainz", extra_ids=extra))
    return ExternalId.objects.get(source="musicbrainz", external_id=group).item


def test_a_release_is_known_once_an_album_was_stored_with_its_id() -> None:
    ledger = DbLedger()
    assert ledger.is_known(mbid(1, 1)) is False

    stored_album(mbid(2, 1), release=mbid(1, 1))

    assert ledger.is_known(mbid(1, 1)) is True
    assert ledger.is_known(mbid(1, 2)) is False


def test_the_ledger_knows_which_release_groups_already_have_an_item() -> None:
    ledger = DbLedger()
    stored_album(mbid(2, 1))

    assert ledger.group_item_exists(mbid(2, 1)) is True
    assert ledger.group_item_exists(mbid(2, 2)) is False


def test_another_release_of_a_stored_album_can_be_linked_to_it() -> None:
    ledger = DbLedger()
    item = stored_album(mbid(2, 1))

    ledger.link_release(mbid(2, 1), mbid(1, 9))
    ledger.link_release(mbid(2, 1), mbid(1, 9))  # linking twice changes nothing

    assert ledger.is_known(mbid(1, 9)) is True
    assert ExternalId.objects.get(source="musicbrainz-release", external_id=mbid(1, 9)).item == item
    assert ExternalId.objects.filter(source="musicbrainz-release").count() == 1


def test_linking_a_release_to_an_unknown_group_does_nothing() -> None:
    DbLedger().link_release(mbid(2, 5), mbid(1, 5))

    assert ExternalId.objects.count() == 0


def test_a_release_id_that_belongs_to_another_item_is_not_taken_over() -> None:
    ledger = DbLedger()
    first = stored_album(mbid(2, 1), release=mbid(1, 1))
    stored_album(mbid(2, 2))

    ledger.link_release(mbid(2, 2), mbid(1, 1))

    assert (
        ExternalId.objects.get(source="musicbrainz-release", external_id=mbid(1, 1)).item == first
    )


def test_rejections_are_remembered_and_can_be_retried() -> None:
    ledger = DbLedger()
    assert ledger.is_skipped(mbid(1, 1)) is False

    ledger.mark_skipped(mbid(1, 1), "not_studio_album")
    ledger.mark_skipped(mbid(1, 1), "not_found")  # a later reason replaces the earlier one

    assert ledger.is_skipped(mbid(1, 1)) is True
    assert SkippedRecord.objects.get().reason == "not_found"
    assert DbLedger(retry_skipped=True).is_skipped(mbid(1, 1)) is False


def test_a_skipped_record_is_unique_per_source_and_id() -> None:
    SkippedRecord.objects.create(source="musicbrainz-release", external_id="x", reason="a")

    with pytest.raises(IntegrityError), transaction.atomic():
        SkippedRecord.objects.create(source="musicbrainz-release", external_id="x", reason="b")

    SkippedRecord.objects.create(source="other", external_id="x", reason="a")


# --- the real clients, wired together over scripted HTTP -------------------------------------

STUDIO_RELEASE, STUDIO_GROUP = mbid(1, 10), mbid(2, 10)
LIVE_RELEASE, LIVE_GROUP = mbid(1, 20), mbid(2, 20)


def scripted_world():
    """Three Last.fm albums under one tag: a studio album, a live album, and one with no id."""

    def json_response(payload: object, status: int = 200):
        from catalog.http import HttpResponse

        return HttpResponse(status, {}, json.dumps(payload).encode())

    def handler(method: str, url: str, headers: dict[str, str], body: str):
        from catalog.http import HttpResponse

        host, path = urlsplit(url).netloc, urlsplit(url).path
        if host == "ws.audioscrobbler.com":
            form = {k: v[0] for k, v in parse_qs(body).items()}
            if form["method"] == "tag.gettopalbums":
                if form["tag"] == "rock" and form["page"] == "1":
                    albums = [
                        {
                            "name": "Studio One",
                            "mbid": STUDIO_RELEASE,
                            "artist": {"name": "Band A"},
                        },
                        {"name": "Live One", "mbid": LIVE_RELEASE, "artist": {"name": "Band B"}},
                        {"name": "No Id", "mbid": "", "artist": {"name": "Band C"}},
                    ]
                else:
                    albums = []
                return json_response({"albums": {"album": albums}})
            listeners = "90000" if form["mbid"] == STUDIO_RELEASE else "70000"
            return json_response(
                {
                    "album": {
                        "name": "X",
                        "artist": "Y",
                        "listeners": listeners,
                        "tags": {"tag": [{"name": "indie"}, {"name": "night drive"}]},
                    }
                }
            )
        if host == "musicbrainz.org":
            if path.startswith("/ws/2/release/"):
                release = path.rsplit("/", 1)[1]
                group = STUDIO_GROUP if release == STUDIO_RELEASE else LIVE_GROUP
                return json_response({"id": release, "release-group": {"id": group}})
            group = path.rsplit("/", 1)[1]
            studio = group == STUDIO_GROUP
            return json_response(
                {
                    "id": group,
                    "title": "Studio One" if studio else "Live One",
                    "primary-type": "Album",
                    "secondary-types": [] if studio else ["Live"],
                    "first-release-date": "1997-05",
                    "artist-credit": [{"name": "Band A" if studio else "Band B", "joinphrase": ""}],
                    "relations": [
                        {
                            "type": "wikidata",
                            "url": {"resource": "https://www.wikidata.org/wiki/Q77"},
                        }
                    ]
                    if studio
                    else [],
                }
            )
        if host == "coverartarchive.org":
            return HttpResponse(307, {"Location": "https://archive.org/x.jpg"}, b"")
        if host == "www.wikidata.org":
            return json_response(
                {"entities": {"Q77": {"sitelinks": {"enwiki": {"title": "Studio One"}}}}}
            )
        if host == "en.wikipedia.org":
            return json_response(
                {"query": {"pages": [{"title": "Studio One", "extract": "An invented album."}]}}
            )
        raise AssertionError(f"unexpected request to {url}")

    return ScriptedTransport(handler)


def build_source(transport: ScriptedTransport, ledger: DbLedger | None = None) -> AlbumSource:
    clock = FakeClock()
    common = {"user_agent": AGENT, "transport": transport, "sleep": clock.sleep}

    def throttle() -> Throttle:
        return Throttle(0, clock=clock.time, sleep=clock.sleep)

    return AlbumSource(
        lastfm=LastFmClient(api_key="k", throttle=throttle(), **common),
        musicbrainz=MusicBrainzClient(throttle=throttle(), **common),
        coverart=CoverArtArchive(throttle=throttle(), **common),
        wikipedia=WikipediaClient(throttle=throttle(), **common),
        ledger=ledger or DbLedger(),
        tags=["rock"],
        min_listeners=80000,
        mid_tail_min_listeners=50000,
        batch_size=20,
    )


def calls_to(transport: ScriptedTransport, host: str) -> list[dict]:
    return [c for c in transport.calls if urlsplit(c["url"]).netloc == host]


def test_the_real_clients_produce_a_stored_studio_album_and_reject_the_rest() -> None:
    transport = scripted_world()
    source = build_source(transport)

    stats = ingest_items(source, limit=10, mid_tail_percent=50)

    assert stats.created == 1
    item = Item.objects.get()
    assert item.title == "Studio One"
    assert item.release_year == 1997
    assert item.cover_url == f"https://coverartarchive.org/release-group/{STUDIO_GROUP}/front-500"
    assert item.summary == "An invented album."
    assert (
        item.combined_text
        == "Studio One\nBy: Band A\nTags: indie, night drive\n\nAn invented album."
    )
    assert dict(SkippedRecord.objects.values_list("external_id", "reason")) == {
        LIVE_RELEASE: "not_studio_album"
    }
    # The live album (70,000 listeners) is in the mid-tail band, so the mid-tail stream met it.
    assert source.drops["no_mbid"] == 1
    assert source.drops["not_studio_album"] == 1
    assert all(c["headers"]["User-Agent"] == AGENT for c in transport.calls)


def test_a_second_run_only_does_new_work() -> None:
    transport = scripted_world()
    ingest_items(build_source(transport), limit=10, mid_tail_percent=50)
    musicbrainz_calls = len(calls_to(transport, "musicbrainz.org"))
    coverart_calls = len(calls_to(transport, "coverartarchive.org"))
    wikimedia_calls = len(calls_to(transport, "en.wikipedia.org"))

    second = build_source(transport)  # a fresh source: it remembers nothing but the database
    stats = ingest_items(second, limit=10, mid_tail_percent=50)

    assert stats.created == 0
    assert Item.objects.count() == 1
    assert len(calls_to(transport, "musicbrainz.org")) == musicbrainz_calls
    assert len(calls_to(transport, "coverartarchive.org")) == coverart_calls
    assert len(calls_to(transport, "en.wikipedia.org")) == wikimedia_calls
    assert second.drops["already_ingested"] == 1
    assert second.drops["previously_skipped"] == 1


def test_retrying_skipped_albums_looks_at_them_again() -> None:
    transport = scripted_world()
    ingest_items(build_source(transport), limit=10, mid_tail_percent=50)
    before = len(calls_to(transport, "musicbrainz.org"))

    retry = build_source(transport, DbLedger(retry_skipped=True))
    ingest_items(retry, limit=10, mid_tail_percent=50)

    assert len(calls_to(transport, "musicbrainz.org")) > before
    assert retry.drops["previously_skipped"] == 0
    assert retry.drops["not_studio_album"] == 1
