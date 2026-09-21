from collections.abc import Iterator
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from catalog.management.commands.ingest_albums import _REASONS
from catalog.models import Item
from catalog.sources.base import ItemRecord, SourceUnavailable
from tests.factories import AlbumWorld, make_item_record

pytestmark = pytest.mark.django_db

PATCH = "catalog.management.commands.ingest_albums.get_album_source"


def run(*args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("ingest_albums", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@override_settings(MID_TAIL_PERCENT=0, INGEST_LIMIT=0)
def test_ingest_albums_reports_what_it_did_and_why_others_were_left_out() -> None:
    world = AlbumWorld()
    world.add(1)
    world.add(2)
    world.add(3, with_mbid=False)
    world.add(4, studio=False)
    world.add(5, tags=())
    with mock.patch(PATCH, return_value=world.source):
        out, err = run("--limit", "5")

    assert "Ingesting up to 5 albums from Last.fm and MusicBrainz" in out
    assert "Done: 2 created, 0 updated, 0 unchanged, 0 skipped (missing tags)." in out
    assert "Albums with tags: 2 of 2." in out
    assert "Albums left out, by reason:" in out
    assert "no MusicBrainz id on Last.fm (never matched by title)" in out
    assert "not a studio album (live, compilation, EP, single...)" in out
    assert "no usable tags" in out
    assert "python manage.py embed_items" in out
    assert err == ""
    assert Item.objects.count() == 2


@override_settings(MID_TAIL_PERCENT=0)
def test_no_reason_block_is_printed_when_nothing_was_left_out() -> None:
    world = AlbumWorld()
    world.add(1)
    with mock.patch(PATCH, return_value=world.source):
        out, _ = run("--limit", "1")

    assert "left out" not in out


def test_retry_skipped_is_passed_through_and_off_by_default() -> None:
    world = AlbumWorld()
    with mock.patch(PATCH, return_value=world.source) as get_source:
        run("--limit", "1")
        run("--limit", "1", "--retry-skipped")

    assert [c.kwargs["retry_skipped"] for c in get_source.call_args_list] == [False, True]


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_a_limit_below_one_is_rejected(bad: str) -> None:
    with pytest.raises(CommandError, match="at least 1"):
        run("--limit", bad)


@pytest.mark.parametrize(
    ("api_key", "contact", "message"),
    [
        ("", "me@example.com", "LASTFM_API_KEY"),
        ("key", "", "CONTACT_EMAIL"),
        ("key", "bad contact", "CONTACT_EMAIL"),
    ],
)
def test_missing_or_unusable_settings_stop_the_command_with_a_clear_message(
    api_key: str, contact: str, message: str
) -> None:
    with (
        override_settings(LASTFM_API_KEY=api_key, CONTACT_EMAIL=contact),
        pytest.raises(CommandError, match=message),
    ):
        run()


@override_settings(MID_TAIL_PERCENT=0)
def test_a_source_failure_keeps_earlier_albums_and_says_how_to_continue() -> None:
    class Failing:
        def popular(self) -> Iterator[ItemRecord]:
            yield make_item_record(
                "1", media_type="album", source="musicbrainz", keywords=("rock",)
            )
            raise SourceUnavailable("MusicBrainz is unavailable")

        def mid_tail(self) -> Iterator[ItemRecord]:
            return iter(())

    with mock.patch(PATCH, return_value=Failing()), pytest.raises(CommandError) as excinfo:
        run("--limit", "5")

    assert "MusicBrainz is unavailable" in str(excinfo.value)
    assert "Albums already ingested are kept" in str(excinfo.value)
    assert Item.objects.count() == 1


def test_every_reason_the_pipeline_can_give_has_a_readable_explanation() -> None:
    import re
    from pathlib import Path

    source = Path("catalog/sources/albums.py").read_text(encoding="utf-8")
    used = set(re.findall(r'_(?:drop|skip)\([^,]+, ?"([a-z_]+)"', source))
    used |= set(re.findall(r'self\._drop\("([a-z_]+)"', source))

    assert used, "expected to find drop reasons in the pipeline"
    assert used <= set(_REASONS), used - set(_REASONS)


def test_progress_messages_from_the_pipeline_appear_in_the_command_output() -> None:
    world = AlbumWorld()
    with mock.patch(PATCH, return_value=world.source) as get_source:
        out, _ = StringIO(), StringIO()
        call_command("ingest_albums", "--limit", "1", stdout=out, stderr=StringIO())
        get_source.call_args.kwargs["heartbeat"]("  mid-tail: checked 25 albums on Last.fm...")

    assert "mid-tail: checked 25 albums on Last.fm..." in out.getvalue()


@override_settings(MID_TAIL_PERCENT=100)
def test_a_mid_tail_search_that_gave_up_says_what_to_change() -> None:
    world = AlbumWorld(mid_tail_max_scan=2)
    for n in range(1, 8):
        world.add(n, listeners=500)
    with mock.patch(PATCH, return_value=world.source):
        out, err = run("--limit", "10")

    assert "The mid-tail search gave up after checking 2 albums on Last.fm" in err
    assert "ALBUM_MID_TAIL_START_PAGE" in err
    assert "MID_TAIL_PERCENT=0" in err
    assert "Done: 2 created" in out  # what it found before giving up is kept
