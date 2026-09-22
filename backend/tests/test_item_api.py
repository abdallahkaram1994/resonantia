"""GET /api/items/<id>/ and GET /api/items/<id>/similar/ (SPEC section 8)."""

from datetime import UTC, datetime

import pytest
from django.test import Client, override_settings

from catalog.models import EMBEDDING_DIMENSIONS, Item, MediaType, Score

pytestmark = pytest.mark.django_db

MODEL = "test-model"
FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def vec(*head: float) -> list[float]:
    return [*head] + [0.0] * (EMBEDDING_DIMENSIONS - len(head))


def add(
    title: str,
    vector: list[float] | None = None,
    media_type: str = MediaType.FILM,
    *,
    model: str = MODEL,
    dim: int | None = None,
    details: dict | None = None,
) -> Item:
    item = Item(media_type=media_type, title=title, release_year=2001, details=details or {})
    item.set_combined_text(title)
    if vector is not None:
        item.set_embedding(vector, model)
    if dim is not None:
        item.embedding_dim = dim
    item.save()
    return item


# --- item detail ---------------------------------------------------------------------------


def test_the_detail_endpoint_returns_the_items_fields(client: Client) -> None:
    item = add(
        "The Film",
        details={"genres": ["Drama"], "keywords": ["rain"], "tagline": "", "runtime": 100},
    )
    Score.objects.create(
        item=item, source="tmdb", value=7.4, vote_count=1500, fetched_at=FETCHED_AT
    )

    body = client.get(f"/api/items/{item.id}/").json()

    assert body["id"] == item.id
    assert body["media_type"] == "film"
    assert body["title"] == "The Film"
    assert body["details"]["genres"] == ["Drama"]
    assert body["scores"] == [{"source": "tmdb", "value": 7.4, "vote_count": 1500}]


def test_a_missing_item_is_a_404(client: Client) -> None:
    response = client.get("/api/items/999999/")

    assert response.status_code == 404


@pytest.mark.parametrize("bad", ["abc", "-1", "1.5"])
def test_a_non_integer_id_is_not_found(client: Client, bad: str) -> None:
    assert client.get(f"/api/items/{bad}/").status_code == 404


def test_an_unembedded_item_still_has_a_detail_page(client: Client) -> None:
    item = add("Not yet embedded", vector=None)

    response = client.get(f"/api/items/{item.id}/")

    assert response.status_code == 200
    assert response.json()["title"] == "Not yet embedded"


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_the_detail_endpoint_only_allows_get(client: Client, method: str) -> None:
    item = add("The Film")

    assert getattr(client, method)(f"/api/items/{item.id}/").status_code == 405


# --- more like this --------------------------------------------------------------------------


def test_similar_items_are_grouped_by_media_type_in_catalog_order(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0))
    add("Album match", vec(1.0, 0.5), MediaType.ALBUM)
    add("Game match", vec(1.0, 0.3), MediaType.GAME)
    add("Film match", vec(1.0, 0.1))

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    assert [g["media_type"] for g in body["groups"]] == ["film", "game", "album"]


def test_the_item_itself_never_appears_in_its_own_similar_list(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0))

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    assert body["groups"] == []
    ids = [r["id"] for g in body["groups"] for r in g["results"]]
    assert origin.id not in ids


def test_the_nearest_items_come_first_within_each_group(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0))
    add("Far", vec(0.0, 1.0))
    add("Exact-ish", vec(1.0, 0.01))
    add("Middle", vec(1.0, 0.5))

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    (group,) = body["groups"]
    assert [r["title"] for r in group["results"]] == ["Exact-ish", "Middle", "Far"]


def test_only_vectors_of_the_items_own_model_and_dimension_are_compared(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0), model="model-a")
    add("Same model", vec(1.0, 0.1), model="model-a")
    add("Other model", vec(1.0), model="model-b")
    add("Other dim", vec(1.0), model="model-a", dim=512)
    add("Not embedded", vector=None)

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    titles = [r["title"] for g in body["groups"] for r in g["results"]]
    assert titles == ["Same model"]


def test_an_item_with_no_vector_gets_an_empty_but_successful_response(client: Client) -> None:
    origin = add("Not embedded", vector=None)
    add("Anything", vec(1.0))

    response = client.get(f"/api/items/{origin.id}/similar/")

    assert response.status_code == 200
    assert response.json() == {"groups": []}


def test_a_missing_items_similar_list_is_a_404(client: Client) -> None:
    assert client.get("/api/items/999999/similar/").status_code == 404


def test_the_total_is_configurable_and_split_across_types_by_similarity_not_evenly(
    client: Client,
) -> None:
    origin = add("Origin", vector=vec(1.0))
    for i in range(10):
        add(f"Film {i}", vec(1.0, 0.01 * i))
    add("One album", vec(1.0, 5.0), MediaType.ALBUM)  # far away

    with override_settings(ITEM_SIMILAR_LIMIT=5):
        five = client.get(f"/api/items/{origin.id}/similar/").json()
    with override_settings(ITEM_SIMILAR_LIMIT=3):
        three = client.get(f"/api/items/{origin.id}/similar/").json()

    assert sum(len(g["results"]) for g in five["groups"]) == 5
    assert sum(len(g["results"]) for g in three["groups"]) == 3
    assert [g["media_type"] for g in five["groups"]] == ["film"]  # the album missed the top 5


def test_a_group_only_appears_when_it_has_at_least_one_match(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0))
    add("Only a film", vec(1.0, 0.1))

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    assert [g["media_type"] for g in body["groups"]] == ["film"]


def test_the_result_shape_matches_search_results(client: Client) -> None:
    origin = add("Origin", vector=vec(1.0))
    add("Match", vec(1.0, 0.1))

    body = client.get(f"/api/items/{origin.id}/similar/").json()

    result = body["groups"][0]["results"][0]
    assert set(result) == {"id", "media_type", "title", "release_year", "cover_url", "score"}
