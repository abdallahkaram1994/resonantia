from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from catalog.embedding.base import EmbeddingRateLimited, EmbeddingRequestError
from catalog.models import Item
from catalog.sources.base import FilmRecord, SourceUnavailable
from tests.factories import FakeEmbedder, FakeFilmSource, make_record

pytestmark = pytest.mark.django_db

INGEST = "catalog.management.commands.ingest_films.get_film_source"
EMBED = "catalog.management.commands.embed_items.get_embedder"


def run(command: str, *args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@override_settings(FILM_MID_TAIL_PERCENT=0, INGEST_LIMIT=0)
def test_ingest_reports_what_it_did_and_points_to_the_next_step() -> None:
    source = FakeFilmSource(
        popular=[make_record(i, fetched_at=datetime.now(UTC)) for i in (1, 2, 3)]
    )
    with mock.patch(INGEST, return_value=source):
        out, err = run("ingest_films", "--limit", "3")

    assert "Done: 3 created, 0 updated, 0 unchanged, 0 skipped" in out
    assert "Films with keywords: 3 of 3." in out
    assert "Oldest TMDB fetch in the catalog:" in out
    assert "python manage.py embed_items" in out
    assert err == ""


@override_settings(FILM_MID_TAIL_PERCENT=0, INGEST_LIMIT=2, CATALOG_TARGET_PER_TYPE=50)
def test_ingest_limit_comes_from_the_flag_then_the_env_setting_then_the_target() -> None:
    def ingested(*args: str) -> int:
        Item.objects.all().delete()
        source = FakeFilmSource(popular=[make_record(i) for i in range(1, 11)])
        with mock.patch(INGEST, return_value=source):
            run("ingest_films", *args)
        return Item.objects.count()

    assert ingested() == 2
    assert ingested("--limit", "4") == 4
    with override_settings(INGEST_LIMIT=0):
        assert ingested() == 10  # fewer than the target of 50 exist


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_ingest_rejects_a_limit_below_one(bad: str) -> None:
    with pytest.raises(CommandError, match="at least 1"):
        run("ingest_films", "--limit", bad)


@override_settings(TMDB_READ_ACCESS_TOKEN="")
def test_ingest_needs_a_token() -> None:
    with pytest.raises(CommandError, match="TMDB_READ_ACCESS_TOKEN"):
        run("ingest_films")


@override_settings(FILM_MID_TAIL_PERCENT=0)
def test_a_source_failure_keeps_earlier_films_and_says_how_to_continue() -> None:
    class Failing:
        def popular_films(self) -> Iterator[FilmRecord]:
            yield make_record(1)
            yield make_record(2)
            raise SourceUnavailable("TMDB is unavailable")

        def mid_tail_films(self) -> Iterator[FilmRecord]:
            return iter(())

    with mock.patch(INGEST, return_value=Failing()), pytest.raises(CommandError) as excinfo:
        run("ingest_films", "--limit", "5")

    assert "TMDB is unavailable" in str(excinfo.value)
    assert "run the command again" in str(excinfo.value)
    assert Item.objects.count() == 2


@override_settings(FILM_MID_TAIL_PERCENT=0, TMDB_MAX_CACHE_DAYS=150)
def test_ingest_warns_when_catalog_data_is_past_the_refresh_window() -> None:
    old = datetime.now(UTC) - timedelta(days=200)
    source = FakeFilmSource(popular=[make_record(1, fetched_at=old)])
    with mock.patch(INGEST, return_value=source):
        _, err = run("ingest_films", "--limit", "1")

    assert "200 days ago" in err
    assert "6 months" in err


@override_settings(GEMINI_API_KEY="")
def test_embed_needs_an_api_key() -> None:
    with pytest.raises(CommandError, match="GEMINI_API_KEY"):
        run("embed_items")


def test_embed_rejects_a_limit_below_one() -> None:
    with pytest.raises(CommandError, match="at least 1"):
        run("embed_items", "--limit", "0")


def test_embed_reports_progress_and_what_remains() -> None:
    for i in (1, 2, 3):
        Item.objects.create(
            media_type="film", title=f"F{i}", combined_text=f"F{i}", content_hash=f"h{i}"
        )
    with mock.patch(EMBED, return_value=FakeEmbedder()):
        out, _ = run("embed_items", "--limit", "2")

    assert "3 items need embedding with test-model." in out
    assert "Embedded 2; 1 remaining." in out
    assert "Stopped early" not in out


@pytest.mark.parametrize(
    ("quota_exhausted", "expected"),
    [(True, "daily quota"), (False, "rate limiting")],
)
def test_embed_explains_why_it_stopped_early(quota_exhausted: bool, expected: str) -> None:
    for i in (1, 2, 3):
        Item.objects.create(
            media_type="film", title=f"F{i}", combined_text=f"F{i}", content_hash=f"h{i}"
        )
    limited = EmbeddingRateLimited("limit", retry_after=None, quota_exhausted=quota_exhausted)
    with mock.patch(EMBED, return_value=FakeEmbedder(fail_on=2, error=limited)):
        out, _ = run("embed_items")

    assert "Embedded 1; 2 remaining." in out
    assert "Stopped early" in out
    assert expected in out


def test_embed_turns_provider_errors_into_a_clear_failure() -> None:
    Item.objects.create(media_type="film", title="F", combined_text="F", content_hash="h")
    bad = EmbeddingRequestError("HTTP 400: API key not valid")
    with (
        mock.patch(EMBED, return_value=FakeEmbedder(fail_on=1, error=bad)),
        pytest.raises(CommandError) as excinfo,
    ):
        run("embed_items")

    assert "API key not valid" in str(excinfo.value)
    assert "run the command again" in str(excinfo.value)
