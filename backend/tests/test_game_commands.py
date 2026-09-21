from collections.abc import Iterator
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from catalog.models import Item, MediaType
from catalog.sources.base import ItemRecord, SourceUnavailable
from tests.factories import FakeItemSource, make_item_record

pytestmark = pytest.mark.django_db

PATCH = "catalog.management.commands.ingest_games.get_game_source"


def run(*args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("ingest_games", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@override_settings(MID_TAIL_PERCENT=0, INGEST_LIMIT=0)
def test_ingest_games_reports_what_it_did_and_points_to_the_next_step() -> None:
    source = FakeItemSource(popular=[make_item_record(str(i)) for i in (1, 2, 3)])
    with mock.patch(PATCH, return_value=source):
        out, err = run("--limit", "3")

    assert "Ingesting up to 3 games from IGDB" in out
    assert "Done: 3 created, 0 updated, 0 unchanged, 0 skipped" in out
    assert "Games with themes or keywords: 3 of 3." in out
    assert "python manage.py embed_items" in out
    assert err == ""
    assert set(Item.objects.values_list("media_type", flat=True)) == {MediaType.GAME}


@override_settings(MID_TAIL_PERCENT=0, INGEST_LIMIT=2, CATALOG_TARGET_PER_TYPE=50)
def test_the_limit_comes_from_the_flag_then_the_env_setting_then_the_target() -> None:
    def ingested(*args: str) -> int:
        Item.objects.all().delete()
        source = FakeItemSource(popular=[make_item_record(str(i)) for i in range(1, 11)])
        with mock.patch(PATCH, return_value=source):
            run(*args)
        return Item.objects.count()

    assert ingested() == 2
    assert ingested("--limit", "4") == 4
    with override_settings(INGEST_LIMIT=0):
        assert ingested() == 10


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_a_limit_below_one_is_rejected(bad: str) -> None:
    with pytest.raises(CommandError, match="at least 1"):
        run("--limit", bad)


@pytest.mark.parametrize(
    ("client_id", "client_secret"),
    [("", ""), ("id", ""), ("", "secret")],
)
def test_both_twitch_credentials_are_required(client_id: str, client_secret: str) -> None:
    with (
        override_settings(TWITCH_CLIENT_ID=client_id, TWITCH_CLIENT_SECRET=client_secret),
        pytest.raises(CommandError, match="TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET"),
    ):
        run()


@override_settings(MID_TAIL_PERCENT=0)
def test_a_source_failure_keeps_earlier_games_and_says_how_to_continue() -> None:
    class Failing:
        def popular(self) -> Iterator[ItemRecord]:
            yield make_item_record("1")
            yield make_item_record("2")
            raise SourceUnavailable("IGDB is unavailable")

        def mid_tail(self) -> Iterator[ItemRecord]:
            return iter(())

    with mock.patch(PATCH, return_value=Failing()), pytest.raises(CommandError) as excinfo:
        run("--limit", "5")

    assert "IGDB is unavailable" in str(excinfo.value)
    assert "Games already ingested are kept" in str(excinfo.value)
    assert Item.objects.count() == 2


@override_settings(MID_TAIL_PERCENT=0)
def test_thin_games_are_skipped_and_counted() -> None:
    source = FakeItemSource(
        popular=[make_item_record("1", summary=""), make_item_record("2")],
    )
    with mock.patch(PATCH, return_value=source):
        out, _ = run("--limit", "1")

    assert "1 created" in out
    assert "1 skipped (missing summary, genres and themes)" in out
