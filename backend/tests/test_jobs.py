"""What a background job does, tested without any queue: the queue is covered in
test_worker_tasks.py."""

from unittest import mock

import pytest
from django.test import override_settings

from catalog import jobs
from catalog.embed import EmbedStats
from catalog.ingest import IngestStats
from tests.factories import FakeFilmSource, FakeItemSource, make_item_record

pytestmark = pytest.mark.django_db


@override_settings(INGEST_LIMIT=7, CATALOG_TARGET_PER_TYPE=50)
def test_the_limit_is_the_given_one_then_the_env_setting_then_the_target() -> None:
    assert jobs.resolve_limit(3) == 3
    assert jobs.resolve_limit(None) == 7
    with override_settings(INGEST_LIMIT=0):
        assert jobs.resolve_limit(None) == 50


@override_settings(INGEST_LIMIT=7)
def test_a_limit_of_zero_is_not_replaced_by_the_default() -> None:
    assert jobs.resolve_limit(0) == 0


@pytest.mark.parametrize(
    ("media", "factory"),
    [("games", "get_game_source"), ("albums", "get_album_source")],
)
@override_settings(MID_TAIL_PERCENT=0)
def test_games_and_albums_are_ingested_from_their_own_source(media: str, factory: str) -> None:
    source = FakeItemSource(popular=[make_item_record(str(i)) for i in (1, 2, 3)])
    others = {"get_film_source", "get_game_source", "get_album_source"} - {factory}

    with mock.patch(f"catalog.jobs.{factory}", return_value=source) as chosen:
        with mock.patch.multiple("catalog.jobs", **{name: mock.DEFAULT for name in others}) as rest:
            stats = jobs.ingest(media, 2)

    assert isinstance(stats, IngestStats)
    assert stats.created == 2
    chosen.assert_called_once_with()
    assert not any(m.called for m in rest.values())


@override_settings(MID_TAIL_PERCENT=0)
def test_films_are_ingested_through_the_film_adapter() -> None:
    with mock.patch("catalog.jobs.get_film_source", return_value=FakeFilmSource([])) as factory:
        stats = jobs.ingest("films", 5)

    factory.assert_called_once_with()
    assert stats.created == 0


def test_an_unknown_media_type_is_refused_before_any_source_is_built() -> None:
    with (
        mock.patch("catalog.jobs.get_game_source") as games,
        pytest.raises(ValueError, match="Unknown media type 'books'"),
    ):
        jobs.ingest("books", 1)

    games.assert_not_called()


@override_settings(MID_TAIL_PERCENT=30)
def test_the_ingest_gets_the_limit_and_the_mid_tail_share_from_settings() -> None:
    with (
        mock.patch("catalog.jobs.get_game_source", return_value=object()),
        mock.patch("catalog.jobs.ingest_items", return_value=IngestStats()) as ingest_items,
    ):
        jobs.ingest("games", 12)

    assert ingest_items.call_args.kwargs == {"limit": 12, "mid_tail_percent": 30}


def test_embedding_passes_the_limit_to_the_embedder_it_builds() -> None:
    embedder = object()
    with (
        mock.patch("catalog.jobs.get_embedder", return_value=embedder),
        mock.patch("catalog.jobs.embed_pending", return_value=EmbedStats(embedded=4)) as run,
    ):
        stats = jobs.embed(9)
        jobs.embed()

    assert stats.embedded == 4
    assert run.call_args_list[0] == mock.call(embedder, limit=9)
    assert run.call_args_list[1] == mock.call(embedder, limit=None)
