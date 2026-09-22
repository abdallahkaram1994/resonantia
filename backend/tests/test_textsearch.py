"""catalog.textsearch: the Postgres full-text fallback used only when the embedding provider is
unavailable (SPEC section 7.5). It matches words, not vibes, but must still respect type isolation
and filters exactly like vector search, and it must never crash on hostile-looking input."""

import pytest

from catalog.filters import ActiveFilter, EraFilter, parse_filters
from catalog.models import Item, MediaType
from catalog.textsearch import text_retrieve_by_type, text_search, tokenize

pytestmark = pytest.mark.django_db


def add(title: str, media_type: str = MediaType.FILM, year: int | None = 2001) -> Item:
    item = Item(media_type=media_type, title=title, release_year=year)
    item.set_combined_text(title)
    item.save()
    return item


def titles(hits) -> list[str]:
    return [h.item.title for h in hits]


def search(query: str, media_type: str = MediaType.FILM, limit: int = 10):
    return text_search(tokenize(query), media_type=media_type, keep=None, limit=limit)


# --- tokenizing ----------------------------------------------------------------------------


def test_words_are_lowercased_and_separated() -> None:
    assert tokenize("a Rainy Night Drive") == ["a", "rainy", "night", "drive"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("'; drop table catalog_item; --", ["drop", "table", "catalog", "item"]),
        ("<script>alert(1)</script>", ["script", "alert", "1", "script"]),
        ("🌧️ 夜のドライブ", []),
        ("café naïve", ["caf", "na", "ve"]),
        ("a" * 150 + "​" * 20, ["a" * 150]),
        ("", []),
        ("   ", []),
        ("%00 \x00 null byte", ["00", "null", "byte"]),
    ],
)
def test_only_plain_ascii_words_survive_tokenizing(query: str, expected: list[str]) -> None:
    assert tokenize(query) == expected


def test_tokenizing_cannot_inject_postgres_text_search_query_syntax() -> None:
    # If these characters reached Postgres' own query parser unescaped they would build an
    # OR/negation the visitor never typed; tokenizing strips them all to plain words first.
    assert tokenize("cats | dogs") == ["cats", "dogs"]
    assert tokenize("cats & !dogs") == ["cats", "dogs"]
    assert tokenize('"exact phrase"') == ["exact", "phrase"]


# --- matching --------------------------------------------------------------------------------


def test_a_word_present_in_the_text_is_a_match() -> None:
    add("A Rainy Night Drive")

    assert titles(search("rainy")) == ["A Rainy Night Drive"]


def test_matching_is_case_insensitive_and_stems_english_words() -> None:
    add("Driving in the Rain")

    assert titles(search("DRIVES")) == ["Driving in the Rain"]


def test_any_one_word_matching_is_enough_not_every_word() -> None:
    add("A Rainy Night Drive")

    assert titles(search("a sunny rainy afternoon")) == ["A Rainy Night Drive"]


def test_a_word_not_present_anywhere_matches_nothing() -> None:
    add("A Rainy Night Drive")

    assert search("submarine") == []


def test_an_empty_catalog_matches_nothing() -> None:
    assert search("anything") == []


def test_no_usable_tokens_matches_nothing_rather_than_everything() -> None:
    add("A Rainy Night Drive")

    assert search("🌧️") == []
    assert search("   ") == []


def test_items_that_were_never_embedded_can_still_be_found() -> None:
    # The fallback does not need a vector at all: an item is either in the catalog or it is not.
    item = add("A Rainy Night Drive")
    assert item.embedding is None

    assert titles(search("rainy")) == ["A Rainy Night Drive"]


def test_a_result_carries_the_same_display_fields_as_vector_search() -> None:
    add("A Rainy Night Drive")

    (hit,) = search("rainy")

    assert hit.item.title == "A Rainy Night Drive"
    assert hit.item.media_type == "film"
    assert isinstance(hit.score, float)


# --- ranking -----------------------------------------------------------------------------------


def test_more_matching_words_rank_above_fewer() -> None:
    # Added in the weaker-match-first order, so id order alone would give the wrong answer.
    add("Rainy Afternoon")
    add("Rainy Night Drive")

    assert titles(search("rainy night drive"))[0] == "Rainy Night Drive"


def test_matching_several_different_words_beats_repeating_one_of_them() -> None:
    # Postgres' cover-density rank (ts_rank_cd) rewards repeating one matched word over matching
    # several different ones for an OR query, tested directly against Postgres; plain ts_rank
    # (what this module actually uses) gets this the right way round.
    add("Rain Rain Rain Rain")  # weaker: one word, repeated. Added first, so id order alone
    add("Rain Night")  # would put this one second if rank were not doing the real work.

    assert titles(search("rain night"))[0] == "Rain Night"


def test_ties_are_broken_by_id_so_results_are_stable() -> None:
    first = add("Rain")
    second = add("Rain")

    assert [h.item.id for h in search("rain")] == [first.id, second.id]


def test_the_limit_caps_how_many_matches_come_back() -> None:
    for i in range(5):
        add(f"Rainy {i}")

    assert len(search("rainy", limit=3)) == 3


# --- type isolation and filters -----------------------------------------------------------------


def test_only_the_requested_media_type_is_searched() -> None:
    add("Rainy Night", MediaType.FILM)
    add("Rainy Night", MediaType.GAME)

    assert titles(search("rainy", media_type="game")) == ["Rainy Night"]


def test_a_game_only_filter_removes_games_and_nothing_else() -> None:
    add("Rainy Film", MediaType.FILM)
    add("Rainy Game", MediaType.GAME)
    era = parse_filters({"eras": "1980-1989"})

    pools = text_retrieve_by_type(
        "rainy", media_types=(MediaType.FILM, MediaType.GAME), filters=era, limit=10
    )

    assert titles(pools["film"]) == []  # 2001, outside the era
    assert titles(pools["game"]) == []


def test_an_era_filter_narrows_a_types_own_pool_only() -> None:
    add("Rainy Old", MediaType.FILM, year=1975)
    add("Rainy New", MediaType.FILM, year=1985)
    add("Rainy Game", MediaType.GAME, year=1985)
    active = [ActiveFilter(EraFilter(), ((1980, 1989),))]

    pools = text_retrieve_by_type(
        "rainy", media_types=(MediaType.FILM, MediaType.GAME), filters=active, limit=10
    )

    assert titles(pools["film"]) == ["Rainy New"]
    assert titles(pools["game"]) == ["Rainy Game"]


def test_undated_items_stay_when_no_era_filter_is_active() -> None:
    add("Rainy Undated", year=None)

    pools = text_retrieve_by_type("rainy", media_types=(MediaType.FILM,), filters=[], limit=10)

    assert titles(pools["film"]) == ["Rainy Undated"]


# --- standing across types (for the blended layout) ---------------------------------------------


def test_every_hit_gets_a_standout_score_scaled_within_its_pool() -> None:
    add("Rain Rain Rain")  # three matching words: the strongest hit
    add("Rain")

    pools = text_retrieve_by_type(
        "rain rain rain", media_types=(MediaType.FILM,), filters=[], limit=10
    )
    hits = pools["film"]

    assert hits[0].standout == pytest.approx(1.0)
    assert hits[-1].standout == pytest.approx(0.0)


def test_a_pool_with_one_hit_or_equally_ranked_hits_stands_out_fully() -> None:
    add("Rain")

    pools = text_retrieve_by_type("rain", media_types=(MediaType.FILM,), filters=[], limit=10)

    assert [h.standout for h in pools["film"]] == [1.0]


def test_standing_is_scaled_separately_for_each_media_type() -> None:
    add("Rain Rain Rain", MediaType.FILM)
    add("Rain", MediaType.FILM)
    add("Rain", MediaType.GAME)

    pools = text_retrieve_by_type(
        "rain rain rain", media_types=(MediaType.FILM, MediaType.GAME), filters=[], limit=10
    )

    assert [h.standout for h in pools["film"]] == pytest.approx([1.0, 0.0])
    assert [h.standout for h in pools["game"]] == pytest.approx([1.0])
