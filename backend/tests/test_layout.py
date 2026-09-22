"""The layout rules: single, grouped and blended, and above all that no media type can crowd out
the others in a blended list just because its raw similarity scores sit higher."""

import pytest

from catalog.layout import BLENDED, GROUPED, SINGLE, blend, build_layout
from catalog.models import Item
from catalog.search import SearchHit

_next_id = 0


def hit(
    media_type: str,
    standout: float,
    *,
    score: float = 0.5,
    title: str | None = None,
    id: int | None = None,
) -> SearchHit:
    global _next_id
    if id is None:
        _next_id += 1
        id = _next_id
    item = Item(id=id, media_type=media_type, title=title or f"{media_type} {id}")
    return SearchHit(item, score, standout)


def pool(media_type: str, *standouts: float) -> list[SearchHit]:
    """A pool best first. Raw scores fall a little with each hit and mean nothing across types."""
    return [
        hit(media_type, value, score=0.9 - i * 0.01, title=f"{media_type} {i}")
        for i, value in enumerate(standouts)
    ]


def titles(hits: list[SearchHit]) -> list[str]:
    return [h.item.title for h in hits]


def types_of(hits: list[SearchHit]) -> list[str]:
    return [h.item.media_type for h in hits]


def falling(start: float, count: int, step: float = 0.1) -> list[float]:
    return [start - i * step for i in range(count)]


# --- blending ----------------------------------------------------------------------------------


def test_hits_are_ordered_by_standout_never_by_raw_score() -> None:
    # Films sit at much higher raw scores, but the albums stand out more within their own type.
    films = [hit("film", 1.0, score=0.90, title="film"), hit("film", 0.2, score=0.85)]
    albums = [hit("album", 2.0, score=0.40, title="album"), hit("album", 0.5, score=0.35)]

    blended = blend({"film": films, "album": albums}, limit=4, min_slots=0)

    assert [h.standout for h in blended] == [2.0, 1.0, 0.5, 0.2]
    assert titles(blended)[:2] == ["album", "film"]


def test_a_type_that_stands_out_more_takes_more_of_the_list() -> None:
    films = pool("film", 3.0, 2.8, 2.6, 2.4, 2.2, 2.0)
    albums = pool("album", 1.0, 0.8, 0.6, 0.4, 0.2, 0.0)

    blended = blend({"film": films, "album": albums}, limit=6, min_slots=0)

    assert types_of(blended) == ["film"] * 6


def test_every_type_with_matches_gets_its_reserved_slots_even_when_weak() -> None:
    films = pool("film", *falling(3.0, 10, 0.01))
    games = pool("game", 0.5, 0.3, 0.1)
    albums = pool("album", 0.4, 0.2, 0.0)

    blended = blend({"film": films, "game": games, "album": albums}, limit=9, min_slots=3)

    assert types_of(blended).count("game") == 3
    assert types_of(blended).count("album") == 3
    assert types_of(blended).count("film") == 3
    assert len(blended) == 9


def test_slots_beyond_the_reserved_ones_go_to_the_highest_standout() -> None:
    films = pool("film", 3.0, 2.9, 2.8, 2.7, -1.0)
    games = pool("game", 0.5, 0.4)

    blended = blend({"film": films, "game": games}, limit=4, min_slots=1)

    # Reserved: film 0 and game 0. The other two slots are the best of what is left: films 1 and 2.
    assert titles(blended) == ["film 0", "film 1", "film 2", "game 0"]


def test_the_remaining_slots_go_to_the_best_leftovers_of_any_type_not_the_first_types() -> None:
    films = pool("film", 3.0, -1.0, -1.1)
    games = pool("game", 2.9, 2.8, 2.7)

    blended = blend({"film": films, "game": games}, limit=4, min_slots=1)

    # Reserved: film 0 and game 0. The film leftovers are far below the game leftovers.
    assert titles(blended) == ["film 0", "game 0", "game 1", "game 2"]


def test_the_list_is_never_longer_than_the_limit() -> None:
    pools = {"film": pool("film", *falling(3.0, 50, 0.01)), "game": pool("game", 0.5)}

    assert len(blend(pools, limit=15, min_slots=3)) == 15
    assert len(blend(pools, limit=1, min_slots=3)) == 1


def test_a_short_list_returns_everything_there_is() -> None:
    pools = {"film": pool("film", 2.0, 1.0), "game": pool("game", 0.5)}

    assert len(blend(pools, limit=15, min_slots=3)) == 3


def test_a_type_without_matches_wastes_no_reserved_slots() -> None:
    films = pool("film", *falling(3.0, 10, 0.1))

    blended = blend({"film": films, "game": [], "album": []}, limit=6, min_slots=3)

    assert types_of(blended) == ["film"] * 6


def test_a_type_with_fewer_matches_than_its_reservation_gives_the_rest_away() -> None:
    films = pool("film", *falling(3.0, 10, 0.1))
    games = pool("game", 0.5)

    blended = blend({"film": films, "game": games}, limit=8, min_slots=3)

    assert types_of(blended).count("game") == 1
    assert types_of(blended).count("film") == 7


def test_the_reservation_shrinks_so_it_never_exceeds_the_list() -> None:
    pools = {
        "film": pool("film", 3.0, 2.9, 2.8, 2.7),
        "game": pool("game", 0.4, 0.3, 0.2, 0.1),
        "album": pool("album", 0.4, 0.3, 0.2, 0.1),
    }

    blended = blend(pools, limit=4, min_slots=3)

    # 4 slots for 3 types: one reserved each, and one more for the highest of the rest.
    assert sorted(types_of(blended)) == ["album", "film", "film", "game"]


def test_without_a_reservation_the_highest_standout_wins() -> None:
    films = pool("film", 3.0, 2.0, 1.0)
    games = pool("game", 0.5, 0.1)

    blended = blend({"film": films, "game": games}, limit=3, min_slots=0)

    assert titles(blended) == ["film 0", "film 1", "film 2"]


def test_within_a_type_the_order_is_the_similarity_order() -> None:
    films = pool("film", 2.0, 1.5, 1.0, 0.5)
    albums = pool("album", 1.8, 1.3, 0.8, 0.3)

    blended = blend({"film": films, "album": albums}, limit=8, min_slots=2)

    assert [t for t in titles(blended) if t.startswith("film")] == [f"film {i}" for i in range(4)]
    assert [t for t in titles(blended) if t.startswith("album")] == [f"album {i}" for i in range(4)]


def test_the_blended_list_is_ordered_by_standout_across_types() -> None:
    films = pool("film", 3.0, 2.5, 2.0, 1.5, 1.0, 0.5, -1.0)
    games = pool("game", 0.5, 0.2, 0.1)

    blended = blend({"film": films, "game": games}, limit=8, min_slots=3)

    values = [h.standout for h in blended]
    assert values == sorted(values, reverse=True)
    # game 1 and game 2 are reserved, yet they sit below the films that stand out more.
    assert titles(blended)[-3:] == ["game 0", "game 1", "game 2"]


def test_equal_standout_falls_back_to_raw_score_then_id() -> None:
    a = hit("film", 1.0, score=0.5, id=7)
    b = hit("game", 1.0, score=0.5, id=3)
    c = hit("album", 1.0, score=0.6, id=9)

    ordered = blend({"film": [a], "game": [b], "album": [c]}, limit=3, min_slots=0)
    reversed_input = blend({"album": [c], "game": [b], "film": [a]}, limit=3, min_slots=0)

    assert [h.item.id for h in ordered] == [9, 3, 7]
    assert [h.item.id for h in reversed_input] == [9, 3, 7]


def test_no_matches_at_all_is_an_empty_list() -> None:
    assert blend({"film": [], "game": []}, limit=15, min_slots=3) == []
    assert blend({}, limit=15, min_slots=3) == []


def test_blending_leaves_its_inputs_alone() -> None:
    films = pool("film", 2.0, 1.0)
    games = pool("game", 0.5, 0.4)

    blend({"film": films, "game": games}, limit=2, min_slots=1)

    assert (len(films), len(games)) == (2, 2)


# --- choosing the layout -----------------------------------------------------------------------

LIMITS = {"result_limit": 15, "group_limit": 10, "min_slots": 3}


def many(media_type: str, count: int) -> list[SearchHit]:
    return pool(media_type, *falling(2.0, count, 0.01))


def test_one_enabled_type_is_a_single_ranked_list_up_to_the_limit() -> None:
    layout = build_layout({"game": many("game", 30)}, **LIMITS)

    assert layout.kind == SINGLE
    assert titles(layout.hits) == [f"game {i}" for i in range(15)]
    assert layout.groups == []
    assert layout.notices == []


def test_a_single_type_stays_single_when_the_query_names_it() -> None:
    layout = build_layout({"film": many("film", 3)}, hint="film", **LIMITS)

    assert layout.kind == SINGLE
    assert layout.notices == []


def test_several_types_and_no_type_named_is_one_blended_list() -> None:
    pools = {"film": many("film", 20), "album": many("album", 20)}

    layout = build_layout(pools, **LIMITS)

    assert layout.kind == BLENDED
    assert len(layout.hits) == 15
    assert layout.groups == []
    assert set(types_of(layout.hits)) == {"film", "album"}


def test_a_named_type_makes_grouped_results_with_that_type_first() -> None:
    pools = {"film": many("film", 20), "game": many("game", 20), "album": many("album", 20)}

    layout = build_layout(pools, hint="album", **LIMITS)

    assert layout.kind == GROUPED
    assert [media_type for media_type, _ in layout.groups] == ["album", "film", "game"]
    assert all(len(hits) == 10 for _, hits in layout.groups)
    assert layout.hits == []


def test_grouped_results_keep_similarity_order_inside_each_group() -> None:
    pools = {"film": many("film", 20), "game": many("game", 20)}

    layout = build_layout(pools, hint="game", **LIMITS)

    for _, hits in layout.groups:
        assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_grouped_results_show_only_the_enabled_types_and_keep_empty_ones() -> None:
    pools = {"film": many("film", 3), "album": []}

    layout = build_layout(pools, hint="film", **LIMITS)

    assert layout.kind == GROUPED
    assert [(media_type, len(hits)) for media_type, hits in layout.groups] == [
        ("film", 3),
        ("album", 0),
    ]


def test_the_toggle_wins_over_a_query_that_names_a_switched_off_type() -> None:
    pools = {"film": many("film", 5), "album": many("album", 5)}

    layout = build_layout(pools, hint="game", **LIMITS)

    assert layout.kind == BLENDED
    assert layout.notices == ["Your search mentions games, but games are switched off."]
    assert "game" not in types_of(layout.hits)


def test_a_named_type_that_is_switched_off_leaves_a_single_type_single() -> None:
    layout = build_layout({"film": many("film", 5)}, hint="album", **LIMITS)

    assert layout.kind == SINGLE
    assert layout.notices == ["Your search mentions albums, but albums are switched off."]


@pytest.mark.parametrize("hint", [None, "", "book", "FILM"])
def test_a_hint_that_is_not_a_media_type_is_ignored_without_a_notice(hint: str | None) -> None:
    pools = {"film": many("film", 5), "game": many("game", 5)}

    layout = build_layout(pools, hint=hint, **LIMITS)

    assert layout.kind == BLENDED
    assert layout.notices == []


def test_empty_pools_still_get_a_layout() -> None:
    assert build_layout({"film": []}, **LIMITS).kind == SINGLE
    assert build_layout({"film": [], "game": []}, **LIMITS).kind == BLENDED
    assert build_layout({"film": [], "game": []}, hint="film", **LIMITS).kind == GROUPED


def test_groups_follow_the_catalogs_order_whatever_order_the_pools_arrive_in() -> None:
    pools = {"album": many("album", 2), "game": many("game", 2), "film": many("film", 2)}

    layout = build_layout(pools, hint="game", **LIMITS)

    assert [media_type for media_type, _ in layout.groups] == ["game", "film", "album"]
