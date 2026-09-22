"""The query-embedding cache: a repeated search, or a changed filter, must not spend another
provider request, and the cache must never hand back a vector for the wrong model or text."""

import logging
from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import Client, override_settings

from catalog.embedding.base import (
    EmbeddingRateLimited,
    EmbeddingRequestError,
    EmbeddingUnavailable,
)
from catalog.models import EMBEDDING_DIMENSIONS, Item, MediaType, QueryEmbedding
from catalog.search import embed_query
from catalog.text import content_hash
from tests.factories import StaticEmbedder

pytestmark = pytest.mark.django_db

GET_EMBEDDER = "catalog.views.get_embedder"


def vec(*head: float) -> list[float]:
    return [*head] + [0.0] * (EMBEDDING_DIMENSIONS - len(head))


# --- embed_query -------------------------------------------------------------------------------


def test_the_first_search_asks_the_provider_and_the_next_does_not() -> None:
    embedder = StaticEmbedder(vec(0.25, 0.5))

    first = embed_query(embedder, "a rainy night drive")
    second = embed_query(embedder, "a rainy night drive")

    assert embedder.calls == [(["a rainy night drive"], "query")]
    assert second[:2] == pytest.approx([0.25, 0.5])
    assert len(first) == len(second) == EMBEDDING_DIMENSIONS
    assert QueryEmbedding.objects.count() == 1


def test_a_different_query_is_embedded_separately() -> None:
    embedder = StaticEmbedder(vec(1.0))

    embed_query(embedder, "rain")
    embed_query(embedder, "sun")

    assert [texts for texts, _ in embedder.calls] == [["rain"], ["sun"]]
    assert QueryEmbedding.objects.count() == 2


def test_a_cached_vector_is_the_one_stored_for_that_query() -> None:
    embed_query(StaticEmbedder(vec(1.0)), "rain")
    embed_query(StaticEmbedder(vec(0.0, 1.0)), "sun")

    fresh = StaticEmbedder(vec(0.5, 0.5))  # would answer differently if it were asked
    assert embed_query(fresh, "rain")[:2] == pytest.approx([1.0, 0.0])
    assert embed_query(fresh, "sun")[:2] == pytest.approx([0.0, 1.0])
    assert fresh.calls == []


def test_another_model_never_gets_a_cached_vector_from_this_one() -> None:
    old = StaticEmbedder(vec(1.0), model="old-model")
    new = StaticEmbedder(vec(0.0, 1.0), model="new-model")

    embed_query(old, "rain")
    result = embed_query(new, "rain")

    assert new.calls == [(["rain"], "query")]
    assert result[:2] == pytest.approx([0.0, 1.0])
    assert sorted(QueryEmbedding.objects.values_list("embedding_model", flat=True)) == [
        "new-model",
        "old-model",
    ]
    # Each model still finds its own.
    assert embed_query(old, "rain")[:2] == pytest.approx([1.0, 0.0])


def test_another_dimension_is_a_different_cache_entry() -> None:
    embedder = StaticEmbedder(vec(1.0))
    embed_query(embedder, "rain")
    other = StaticEmbedder(vec(0.0, 1.0))
    other.dimensions = 512

    embed_query(other, "rain")

    assert len(other.calls) == 1
    assert sorted(QueryEmbedding.objects.values_list("embedding_dim", flat=True)) == [
        512,
        EMBEDDING_DIMENSIONS,
    ]


def test_the_query_text_is_not_stored() -> None:
    embed_query(StaticEmbedder(vec(1.0)), "my very private search phrase")

    row = QueryEmbedding.objects.get()
    assert row.text_hash == content_hash("my very private search phrase")
    stored = " ".join(str(value) for value in QueryEmbedding.objects.values().get().values())
    assert "private" not in stored


@pytest.mark.parametrize(
    "error",
    [
        EmbeddingUnavailable("down"),
        EmbeddingRequestError("bad key"),
        EmbeddingRateLimited("slow down", retry_after=5, quota_exhausted=False),
    ],
)
def test_a_provider_error_passes_through_and_is_not_cached(error: Exception) -> None:
    failing = StaticEmbedder(vec(1.0))
    failing.embed = mock.Mock(side_effect=error)  # type: ignore[method-assign]

    with pytest.raises(type(error)):
        embed_query(failing, "rain")

    assert QueryEmbedding.objects.count() == 0
    working = StaticEmbedder(vec(1.0))
    embed_query(working, "rain")
    assert len(working.calls) == 1  # the next search tries the provider again


def test_a_query_stored_by_a_concurrent_search_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    embedder = StaticEmbedder(vec(1.0))

    def lookup_misses_then_another_request_stores_it(*args, **kwargs):
        QueryEmbedding.objects.create(
            text_hash=content_hash("rain"),
            embedding_model=embedder.model,
            embedding_dim=embedder.dimensions,
            embedding=vec(0.0, 1.0),
        )
        return QueryEmbedding.objects.none()

    with (
        mock.patch.object(
            QueryEmbedding.objects,
            "filter",
            side_effect=lookup_misses_then_another_request_stores_it,
        ),
        caplog.at_level(logging.WARNING),
    ):
        vector = embed_query(embedder, "rain")

    assert caplog.records == []  # a race is normal, not something to warn about
    assert vector[:2] == [1.0, 0.0]  # our own answer is returned
    assert QueryEmbedding.objects.count() == 1  # and the other request's row is kept


def test_a_cache_that_cannot_be_written_does_not_fail_the_search(
    caplog: pytest.LogCaptureFixture,
) -> None:
    embedder = StaticEmbedder(vec(1.0))

    with (
        mock.patch.object(QueryEmbedding.objects, "bulk_create", side_effect=DatabaseError("full")),
        caplog.at_level(logging.WARNING),
    ):
        vector = embed_query(embedder, "my very private search phrase")

    assert vector[0] == 1.0
    assert "DatabaseError" in caplog.text
    assert "private" not in caplog.text


# --- through the search endpoint ---------------------------------------------------------------


def add_item(title: str, media_type: str, year: int | None, angle: float = 0.0) -> None:
    item = Item(media_type=media_type, title=title, release_year=year)
    item.set_combined_text(title)
    item.set_embedding(vec(1.0, angle), "test-model")
    item.save()


def search(client: Client, embedder: StaticEmbedder, **params: str):
    with mock.patch(GET_EMBEDDER, return_value=embedder):
        return client.get("/api/search/", {"q": "a rainy night drive", **params})


def test_repeating_a_search_costs_one_embedding_request(client: Client) -> None:
    add_item("Exact", MediaType.FILM, 2000)
    embedder = StaticEmbedder(vec(1.0))

    first = search(client, embedder).json()
    second = search(client, embedder).json()

    assert len(embedder.calls) == 1
    assert first == second


def test_changing_the_filters_on_a_query_costs_nothing_more(client: Client) -> None:
    add_item("Old film", MediaType.FILM, 1975)
    add_item("New film", MediaType.FILM, 1985)
    add_item("A game", MediaType.GAME, 1985)
    embedder = StaticEmbedder(vec(1.0))

    everything = search(client, embedder, types="film").json()
    narrowed = search(client, embedder, types="film", eras="1980-1989").json()
    games = search(client, embedder, types="game").json()

    assert len(embedder.calls) == 1
    assert [r["title"] for r in everything["results"]] == ["Old film", "New film"]
    assert [r["title"] for r in narrowed["results"]] == ["New film"]
    assert [r["title"] for r in games["results"]] == ["A game"]


def test_spelling_out_the_same_query_differently_shares_one_cache_entry(client: Client) -> None:
    embedder = StaticEmbedder(vec(1.0))

    with mock.patch(GET_EMBEDDER, return_value=embedder):
        client.get("/api/search/", {"q": "A  Rainy\tNight Drive"})
        client.get("/api/search/", {"q": " a rainy night drive "})

    assert len(embedder.calls) == 1


def test_a_cached_query_still_works_when_the_provider_is_down(client: Client) -> None:
    add_item("Exact", MediaType.FILM, 2000)
    embedder = StaticEmbedder(vec(1.0))
    search(client, embedder)
    embedder.embed = mock.Mock(side_effect=EmbeddingUnavailable("down"))  # type: ignore[method-assign]

    response = search(client, embedder)

    assert response.status_code == 200
    assert [r["title"] for r in response.json()["results"]] == ["Exact"]
    embedder.embed.assert_not_called()


def test_a_new_query_falls_back_to_text_search_and_caches_nothing(client: Client) -> None:
    embedder = StaticEmbedder(vec(1.0))
    embedder.embed = mock.Mock(side_effect=EmbeddingUnavailable("down"))  # type: ignore[method-assign]

    response = search(client, embedder)

    assert response.status_code == 200
    assert response.json()["mode"] == "text"
    assert QueryEmbedding.objects.count() == 0


def test_a_refused_request_caches_nothing(client: Client) -> None:
    embedder = StaticEmbedder(vec(1.0))

    search(client, embedder, eras="nope")
    with override_settings(SEARCH_MAX_QUERY_LENGTH=5):
        search(client, embedder)

    assert embedder.calls == []
    assert QueryEmbedding.objects.count() == 0


def test_a_new_model_ignores_the_old_models_cached_queries(client: Client) -> None:
    add_item("Exact", MediaType.FILM, 2000)
    search(client, StaticEmbedder(vec(0.0, 1.0), model="old-model"))
    add_item("Match for new", MediaType.FILM, 2000)
    Item.objects.filter(title="Match for new").update(embedding_model="new-model")
    new = StaticEmbedder(vec(1.0), model="new-model")

    response = search(client, new)

    assert len(new.calls) == 1
    assert [r["title"] for r in response.json()["results"]] == ["Match for new"]
