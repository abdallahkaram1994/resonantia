import pytest

from catalog.sources.albums import AlbumSource
from catalog.sources.base import SourceUnavailable
from tests.factories import NOW, AlbumWorld, mbid

pytestmark = pytest.mark.django_db  # the last test ingests into the database


def popular(world: AlbumWorld) -> list:
    return list(world.source.popular())


def test_an_album_flows_through_every_step_into_a_record() -> None:
    world = AlbumWorld()
    release = world.add(1, tags=("alternative rock", "night drive"))

    [record] = popular(world)

    group = mbid(2, 1)
    assert (record.media_type, record.source, record.source_id) == ("album", "musicbrainz", group)
    assert record.title == "Album 1"
    assert record.byline == "Artist 1"
    assert record.release_year == 1997
    assert record.genres == ()
    assert record.keywords == ("alternative rock", "night drive")
    assert record.keywords_label == "Tags"
    assert record.cover_url == f"https://coverartarchive.org/release-group/{group}/front-500"
    assert record.summary == "Album 1 is an invented studio album."
    assert record.score is None  # albums have no score
    assert record.fetched_at == NOW
    assert record.is_embeddable is True
    assert record.extra_ids == (("musicbrainz-release", release), ("wikidata", "Q1001"))
    assert record.field_sources == {
        "details": "musicbrainz+lastfm",
        "cover_url": "coverartarchive",
        "summary": "wikipedia",
    }
    assert record.details["release_group_mbid"] == group
    assert record.details["release_mbid"] == release
    assert record.details["tags"] == ["alternative rock", "night drive"]
    assert record.details["lastfm"]["listeners"] == 5000
    assert record.details["wikipedia"] == {
        "title": "Album 1",
        "url": "https://en.wikipedia.org/wiki/Album_1",
    }


def test_a_missing_cover_and_a_missing_summary_do_not_stop_the_album() -> None:
    world = AlbumWorld()
    world.add(1, cover=False, intro=False)

    [record] = popular(world)

    assert record.cover_url == ""
    assert record.summary == ""
    assert record.details["wikipedia"] is None
    assert record.field_sources == {"details": "musicbrainz+lastfm"}
    assert record.is_embeddable is True  # tags are enough, as the SPEC says


def test_an_album_without_a_wikidata_link_asks_wikipedia_nothing() -> None:
    world = AlbumWorld()
    world.add(1, wikidata=False)

    [record] = popular(world)

    assert record.extra_ids == (("musicbrainz-release", mbid(1, 1)),)
    assert world.wikipedia.calls == [[]]


def test_a_missing_release_year_is_kept_as_none() -> None:
    world = AlbumWorld()
    world.add(1, year=None)

    assert popular(world)[0].release_year is None


def test_the_two_streams_split_albums_by_listener_count() -> None:
    world = AlbumWorld()
    world.add(1, listeners=5000)  # popular
    world.add(2, listeners=1000)  # exactly the popular threshold: popular
    world.add(3, listeners=999)  # top of the mid-tail band
    world.add(4, listeners=100)  # exactly the mid-tail minimum: mid-tail
    world.add(5, listeners=99)  # below both
    world.add(6, listeners=None)  # no listener count

    popular_titles = [r.title for r in world.source.popular()]
    mid_titles = [r.title for r in world.source.mid_tail()]

    assert popular_titles == ["Album 1", "Album 2"]
    assert mid_titles == ["Album 3", "Album 4"]
    assert world.source.drops["below_threshold"] == 1
    assert world.source.drops["no_listener_count"] == 1


def test_an_album_without_a_musicbrainz_id_is_dropped_and_never_matched_by_title() -> None:
    world = AlbumWorld()
    world.add(1, with_mbid=False)
    world.add(2)

    records = popular(world)

    assert [r.title for r in records] == ["Album 2"]
    assert world.source.drops["no_mbid"] == 1
    # Nothing was looked up for the album that had no id: not by id, and not by title.
    assert world.lastfm.info_calls == [mbid(1, 2)]
    assert world.musicbrainz.release_calls == [mbid(1, 2)]
    assert world.musicbrainz.group_calls == [mbid(2, 2)]


def test_an_album_without_usable_tags_is_dropped_before_any_musicbrainz_call() -> None:
    world = AlbumWorld()
    world.add(1, tags=())

    assert popular(world) == []

    assert world.source.drops["no_tags"] == 1
    assert world.musicbrainz.release_calls == []


def test_an_album_unknown_to_lastfm_is_dropped() -> None:
    world = AlbumWorld()
    release = world.add(1)
    world.lastfm.infos[release] = None

    assert popular(world) == []

    assert world.source.drops["lastfm_not_found"] == 1
    assert world.musicbrainz.release_calls == []


def test_live_albums_are_dropped_and_remembered() -> None:
    world = AlbumWorld()
    release = world.add(1, studio=False)

    assert popular(world) == []

    assert world.source.drops["not_studio_album"] == 1
    assert world.ledger.skipped == {release: "not_studio_album"}


def test_releases_without_a_release_group_or_a_record_are_dropped_and_remembered() -> None:
    world = AlbumWorld()
    no_group = world.add(1, release_exists=False)
    gone = world.add(2)
    world.musicbrainz.groups[mbid(2, 2)] = None

    assert popular(world) == []

    assert world.ledger.skipped == {no_group: "no_release_group", gone: "not_found"}


def test_a_rejected_album_is_not_looked_up_again_by_a_later_run() -> None:
    world = AlbumWorld()
    world.add(1, studio=False)
    popular(world)
    musicbrainz_calls = list(world.musicbrainz.release_calls)

    later = AlbumSource(
        lastfm=world.lastfm,  # type: ignore[arg-type]
        musicbrainz=world.musicbrainz,  # type: ignore[arg-type]
        coverart=world.coverart,  # type: ignore[arg-type]
        wikipedia=world.wikipedia,  # type: ignore[arg-type]
        ledger=world.ledger,  # remembers the rejection from the first run
        tags=["rock", "pop"],
        min_listeners=1000,
        mid_tail_min_listeners=100,
        batch_size=20,
    )

    assert list(later.popular()) == []

    assert world.musicbrainz.release_calls == musicbrainz_calls  # no new MusicBrainz call
    assert later.drops["previously_skipped"] == 1


def test_an_album_already_in_the_catalog_costs_no_musicbrainz_call() -> None:
    world = AlbumWorld()
    release = world.add(1)
    world.ledger.known.add(release)

    assert popular(world) == []

    assert world.source.drops["already_ingested"] == 1
    assert world.musicbrainz.release_calls == []


def test_two_releases_of_one_album_make_one_record_that_knows_both() -> None:
    world = AlbumWorld()
    first = world.add(1, group=1)
    second = world.add(2, tag="pop", group=1)

    [record] = popular(world)

    assert record.source_id == mbid(2, 1)
    assert ("musicbrainz-release", first) in record.extra_ids
    assert ("musicbrainz-release", second) in record.extra_ids
    assert world.source.drops["duplicate"] == 1
    assert world.musicbrainz.group_calls == [mbid(2, 1)]  # the second release cost no group lookup


def test_a_second_release_of_an_album_already_stored_is_linked_to_it() -> None:
    world = AlbumWorld()
    release = world.add(1)
    world.ledger.groups.add(mbid(2, 1))

    assert popular(world) == []

    assert world.ledger.linked == [(mbid(2, 1), release)]
    assert world.source.drops["duplicate"] == 1


def test_a_release_listed_under_several_tags_is_handled_once() -> None:
    world = AlbumWorld()
    release = world.add(1, tag="rock")
    world.lastfm.pages[("pop", 1)] = list(world.lastfm.pages[("rock", 1)])

    records = popular(world)

    assert len(records) == 1
    assert world.musicbrainz.release_calls == [release]
    assert world.lastfm.info_calls == [release]


def test_discovery_takes_page_one_of_every_tag_before_page_two() -> None:
    world = AlbumWorld(tags=["rock", "pop"])
    world.add(1, tag="rock", page=1)
    world.add(2, tag="pop", page=1)
    world.add(3, tag="rock", page=2)

    titles = [r.title for r in popular(world)]

    assert titles == ["Album 1", "Album 2", "Album 3"]
    assert world.lastfm.top_calls == [
        ("rock", 1),
        ("pop", 1),
        ("rock", 2),
        ("pop", 2),
        ("rock", 3),
        ("pop", 3),
    ]  # stops once a whole page comes back empty for every tag


def test_the_second_stream_reuses_what_the_first_already_asked_lastfm() -> None:
    world = AlbumWorld()
    world.add(1, listeners=5000)
    world.add(2, listeners=500)
    popular(world)
    top_calls, info_calls = list(world.lastfm.top_calls), list(world.lastfm.info_calls)

    mid = list(world.source.mid_tail())

    assert [r.title for r in mid] == ["Album 2"]
    assert world.lastfm.top_calls == top_calls
    assert world.lastfm.info_calls == info_calls


def test_wikipedia_is_asked_in_batches() -> None:
    world = AlbumWorld(batch_size=3)
    for n in range(1, 8):
        world.add(n)

    records = popular(world)

    assert len(records) == 7
    assert [len(call) for call in world.wikipedia.calls] == [3, 3, 1]
    assert len(world.coverart.calls) == 7


def test_consuming_one_record_only_does_one_batch_of_work() -> None:
    world = AlbumWorld(batch_size=3)
    for n in range(1, 8):
        world.add(n)

    next(world.source.popular())

    assert len(world.musicbrainz.release_calls) == 3
    assert len(world.wikipedia.calls) == 1


def test_a_musicbrainz_outage_stops_the_run_instead_of_dropping_the_album() -> None:
    world = AlbumWorld()
    world.add(1)
    world.musicbrainz.error = SourceUnavailable("MusicBrainz is unavailable")

    with pytest.raises(SourceUnavailable):
        popular(world)

    assert world.ledger.skipped == {}  # an outage is never remembered as a rejection


def test_drops_are_counted_once_even_when_both_streams_see_the_album() -> None:
    world = AlbumWorld()
    world.add(1, listeners=5)  # below both bands
    world.add(2, with_mbid=False)

    popular(world)
    list(world.source.mid_tail())

    assert world.source.drops == {"below_threshold": 1, "no_mbid": 1}


def test_a_record_becomes_a_stored_album_with_the_artist_and_tags_in_its_text() -> None:
    from catalog.ingest import ingest_items
    from catalog.models import ExternalId, Item

    world = AlbumWorld()
    world.add(1, tags=("alternative rock", "night drive"))

    stats = ingest_items(world.source, limit=5, mid_tail_percent=0)

    assert stats.created == 1
    item = Item.objects.get()
    assert item.media_type == "album"
    assert item.combined_text == (
        "Album 1\nBy: Artist 1\nTags: alternative rock, night drive\n\n"
        "Album 1 is an invented studio album."
    )
    assert item.provenance["summary"]["source"] == "wikipedia"
    assert item.provenance["cover_url"]["source"] == "coverartarchive"
    assert sorted(ExternalId.objects.values_list("source", flat=True)) == [
        "musicbrainz",
        "musicbrainz-release",
        "wikidata",
    ]


# --- the mid-tail search: where it starts, when it gives up, and how it reports progress -------


def test_the_mid_tail_search_starts_deeper_than_the_popular_one() -> None:
    world = AlbumWorld(mid_tail_start_page=3)
    world.add(1, page=1, listeners=500)  # would qualify, but page 1 is never visited
    world.add(2, page=3, listeners=500)

    mid = [r.title for r in world.source.mid_tail()]

    assert mid == ["Album 2"]
    assert world.lastfm.top_calls[0] == ("rock", 3)
    assert all(page >= 3 for _, page in world.lastfm.top_calls)


def test_the_popular_search_still_starts_on_page_one() -> None:
    world = AlbumWorld(mid_tail_start_page=8)
    world.add(1, page=1, listeners=5000)

    assert [r.title for r in world.source.popular()] == ["Album 1"]
    assert world.lastfm.top_calls[0] == ("rock", 1)


def test_the_mid_tail_search_gives_up_after_its_scan_cap() -> None:
    world = AlbumWorld(mid_tail_max_scan=5)
    for n in range(1, 21):
        world.add(n, listeners=500)

    records = list(world.source.mid_tail())

    assert len(records) == 5
    assert len(world.lastfm.info_calls) == 5
    assert world.source.gave_up == {"mid-tail": 5}


def test_a_search_that_finishes_within_its_cap_does_not_report_giving_up() -> None:
    world = AlbumWorld(mid_tail_max_scan=50)
    for n in range(1, 4):
        world.add(n, listeners=500)

    assert len(list(world.source.mid_tail())) == 3
    assert world.source.gave_up == {}


def test_the_scan_cap_does_not_limit_the_popular_search() -> None:
    world = AlbumWorld(mid_tail_max_scan=2)
    for n in range(1, 11):
        world.add(n, listeners=5000)

    assert len(list(world.source.popular())) == 10
    assert world.source.gave_up == {}


def test_albums_already_looked_up_do_not_count_toward_the_scan_cap() -> None:
    world = AlbumWorld(mid_tail_max_scan=2)  # fewer than the three albums below
    for n in range(1, 4):
        world.add(n, listeners=500)
    list(world.source.popular())  # looks all three up, and finds none popular
    lookups = len(world.lastfm.info_calls)

    records = list(world.source.mid_tail())

    assert len(records) == 3
    assert len(world.lastfm.info_calls) == lookups  # answered from memory, so nothing to cap
    assert world.source.gave_up == {}


def test_progress_is_reported_while_albums_are_checked_and_identified() -> None:
    messages: list[str] = []
    world = AlbumWorld(heartbeat=messages.append, batch_size=20)
    for n in range(1, 61):
        world.add(n, listeners=500)

    list(world.source.mid_tail())

    assert "  mid-tail: checked 25 albums on Last.fm..." in messages
    assert "  mid-tail: checked 50 albums on Last.fm..." in messages
    assert "  5 albums identified at MusicBrainz so far..." in messages
    assert "  10 albums identified at MusicBrainz so far..." in messages
    assert any("finishing 20 albums" in m for m in messages)


def test_no_progress_callback_is_fine() -> None:
    world = AlbumWorld()
    for n in range(1, 31):
        world.add(n)

    assert len(list(world.source.popular())) == 30


# --- a stream that knows how many albums are needed does not identify more than that -----------


def test_a_small_target_means_a_small_batch() -> None:
    world = AlbumWorld(batch_size=20)
    for n in range(1, 31):
        world.add(n)

    world.source.set_target(3)
    stream = world.source.popular()
    records = [next(stream) for _ in range(3)]  # the consumer takes only what it asked for

    assert len(records) == 3
    assert len(world.musicbrainz.release_calls) == 3  # not a whole batch of twenty
    assert [len(call) for call in world.wikipedia.calls] == [3]


def test_a_target_larger_than_the_batch_still_batches() -> None:
    world = AlbumWorld(batch_size=4)
    for n in range(1, 11):
        world.add(n)

    world.source.set_target(9)
    stream = world.source.popular()
    records = [next(stream) for _ in range(9)]

    assert len(records) == 9
    assert [len(call) for call in world.wikipedia.calls] == [4, 4, 1]


def test_a_target_applies_to_one_stream_only() -> None:
    world = AlbumWorld(batch_size=5)
    for n in range(1, 11):
        world.add(n, listeners=5000)
    for n in range(11, 21):
        world.add(n, listeners=500)

    world.source.set_target(2)
    list(world.source.popular())
    world.wikipedia.calls.clear()
    world.musicbrainz.release_calls.clear()
    stream = world.source.mid_tail()  # no target set: back to the normal batch of five
    next(stream)

    assert len(world.musicbrainz.release_calls) == 5


def test_without_a_target_the_normal_batch_size_is_used() -> None:
    world = AlbumWorld(batch_size=5)
    for n in range(1, 11):
        world.add(n)

    next(world.source.popular())

    assert len(world.musicbrainz.release_calls) == 5
