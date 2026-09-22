"""Standout scores: how far above its own media type's average similarity a hit sits. This is
what makes hits from different types comparable in a blended list."""

import math

import pytest

from catalog.filters import parse_filters
from catalog.models import EMBEDDING_DIMENSIONS, Item, MediaType
from catalog.search import retrieve_by_type, standout_scores

pytestmark = pytest.mark.django_db

MODEL = "test-model"
QUERY = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def unit(angle_degrees: float) -> list[float]:
    """A unit vector at an angle from the query, so its similarity is the cosine of that angle."""
    radians = math.radians(angle_degrees)
    return [math.cos(radians), math.sin(radians)] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


def add(
    title: str,
    media_type: str,
    angle: float | None,
    *,
    year: int | None = 2000,
    model: str = MODEL,
) -> Item:
    item = Item(media_type=media_type, title=title, release_year=year)
    item.set_combined_text(title)
    if angle is not None:
        item.set_embedding(unit(angle), model)
    item.save()
    return item


def pools(media_types=("film", "game", "album"), filters=(), limit=10):
    return retrieve_by_type(
        QUERY, media_types=media_types, filters=filters, model=MODEL, dim=768, limit=limit
    )


def test_a_types_baseline_is_the_mean_and_spread_of_similarity_to_all_its_items() -> None:
    for i, angle in enumerate((0, 60, 60, 90)):  # similarities 1, .5, .5, 0
        add(f"F{i}", MediaType.FILM, angle)

    mean, spread = standout_scores(QUERY, media_type="film", model=MODEL, dim=768)

    assert mean == pytest.approx(0.5)
    assert spread == pytest.approx(math.sqrt(0.125))  # population spread of 1, .5, .5, 0


def test_a_hits_standout_is_its_distance_from_the_mean_in_spreads() -> None:
    for i, angle in enumerate((0, 60, 60, 90)):
        add(f"F{i}", MediaType.FILM, angle)

    hits = pools(("film",))["film"]

    assert [h.item.title for h in hits] == ["F0", "F1", "F2", "F3"]
    spread = math.sqrt(0.125)
    assert [h.standout for h in hits] == pytest.approx(
        [0.5 / spread, 0.0, 0.0, -0.5 / spread], abs=1e-6
    )


def test_the_same_similarity_stands_out_more_in_a_type_where_it_is_rarer() -> None:
    # Films are all fairly close to this query; games are spread far and wide.
    for i, angle in enumerate((40, 42, 44, 46, 48)):
        add(f"F{i}", MediaType.FILM, angle)
    for i, angle in enumerate((40, 60, 70, 80, 89)):
        add(f"G{i}", MediaType.GAME, angle)

    result = pools(("film", "game"))

    film, game = result["film"][0], result["game"][0]
    assert film.score == pytest.approx(game.score)  # the very same raw similarity...
    assert game.standout > film.standout  # ...means more where such a match is uncommon


def test_the_baseline_ignores_the_filters_so_standing_does_not_change_with_them() -> None:
    add("Old", MediaType.FILM, 0, year=1975)
    add("New A", MediaType.FILM, 60, year=1985)
    add("New B", MediaType.FILM, 90, year=1985)

    unfiltered = {h.item.title: h.standout for h in pools(("film",))["film"]}
    narrowed = {
        h.item.title: h.standout
        for h in pools(("film",), filters=parse_filters({"eras": "1980-1989"}))["film"]
    }

    assert set(narrowed) == {"New A", "New B"}
    assert narrowed["New A"] == pytest.approx(unfiltered["New A"])
    assert narrowed["New B"] == pytest.approx(unfiltered["New B"])


def test_a_type_is_compared_only_with_its_own_items() -> None:
    add("F0", MediaType.FILM, 0)
    add("F1", MediaType.FILM, 30)
    add("G0", MediaType.GAME, 89)  # far away, and must not drag the film baseline down

    mean, _ = standout_scores(QUERY, media_type="film", model=MODEL, dim=768)

    assert mean == pytest.approx((1.0 + math.cos(math.radians(30))) / 2)


def test_items_of_another_model_or_without_a_vector_stay_out_of_the_baseline() -> None:
    add("Current", MediaType.FILM, 0)
    add("Also current", MediaType.FILM, 60)
    add("Other model", MediaType.FILM, 90, model="some-other-model")
    add("Not embedded", MediaType.FILM, None)

    mean, _ = standout_scores(QUERY, media_type="film", model=MODEL, dim=768)

    assert mean == pytest.approx(0.75)


def test_a_type_with_nothing_embedded_has_no_baseline() -> None:
    add("Not embedded", MediaType.GAME, None)

    assert standout_scores(QUERY, media_type="game", model=MODEL, dim=768) is None
    assert standout_scores(QUERY, media_type="album", model=MODEL, dim=768) is None


@pytest.mark.parametrize("angles", [(30,), (30, 30, 30)])
def test_a_type_with_no_spread_gets_no_standout_rather_than_a_division_by_zero(
    angles: tuple[int, ...],
) -> None:
    for i, angle in enumerate(angles):
        add(f"F{i}", MediaType.FILM, angle)

    hits = pools(("film",))["film"]

    assert len(hits) == len(angles)
    assert [h.standout for h in hits] == [0.0] * len(angles)


def test_every_enabled_type_gets_its_own_scores() -> None:
    for media_type in ("film", "game", "album"):
        add(f"{media_type} near", media_type, 0)
        add(f"{media_type} far", media_type, 80)

    result = pools()

    assert {t: [h.item.title for h in hits] for t, hits in result.items()} == {
        "film": ["film near", "film far"],
        "game": ["game near", "game far"],
        "album": ["album near", "album far"],
    }
    assert all(hits[0].standout > 0 > hits[1].standout for hits in result.values())


def test_the_raw_similarity_is_still_there_for_ordering_within_a_type() -> None:
    add("Near", MediaType.FILM, 10)
    add("Far", MediaType.FILM, 50)

    near, far = pools(("film",))["film"]

    assert near.score == pytest.approx(math.cos(math.radians(10)))
    assert far.score == pytest.approx(math.cos(math.radians(50)))
