"""The filter registry and per-type retrieval: what each filter keeps, and above all that a filter
scoped to one media type never touches another type's rows."""

from typing import Any

import pytest
from django.db.models import Q

from catalog.filters import (
    FILTERS,
    MAX_ERA_RANGES,
    ActiveFilter,
    EraFilter,
    FilterError,
    parse_filters,
    parse_media_types,
    predicate_for,
)
from catalog.models import EMBEDDING_DIMENSIONS, Item, MediaType
from catalog.search import retrieve, retrieve_by_type

MODEL = "test-model"
ALL_TYPES = (MediaType.FILM, MediaType.GAME, MediaType.ALBUM)


def vec(*head: float) -> list[float]:
    return [*head] + [0.0] * (EMBEDDING_DIMENSIONS - len(head))


def add(title: str, media_type: str, year: int | None, angle: float = 0.0) -> Item:
    item = Item(media_type=media_type, title=title, release_year=year)
    item.set_combined_text(title)
    item.set_embedding(vec(1.0, angle), MODEL)
    item.save()
    return item


class TitleStartsWith:
    """A stand-in for a future type-scoped filter, such as a platform filter for games."""

    name = "prefix"

    def __init__(self, applies_to: set[str]) -> None:
        self.applies_to = frozenset(applies_to)

    def parse(self, params: Any) -> str | None:
        return params.get("prefix")

    def predicate(self, value: str) -> Q:
        return Q(title__startswith=value)


# --- parsing the era filter ------------------------------------------------------------------


def eras(value: str | None) -> Any:
    params = {} if value is None else {"eras": value}
    return EraFilter().parse(params)


@pytest.mark.parametrize("unused", [None, "", "   "])
def test_no_eras_means_the_filter_is_not_in_use(unused: str | None) -> None:
    assert eras(unused) is None


def test_eras_are_year_ranges_in_the_order_given_without_repeats() -> None:
    assert eras("1980-1989") == ((1980, 1989),)
    assert eras(" 1990-1999 , 1980-1989,1990-1999") == ((1990, 1999), (1980, 1989))


def test_an_era_may_span_any_years_in_range() -> None:
    assert eras("1800-2200") == ((1800, 2200),)
    assert eras("1999-1999") == ((1999, 1999),)


@pytest.mark.parametrize(
    "bad",
    [
        "1980",
        "80s",
        "1980-",
        "-1989",
        "1980:1989",
        "1990-1980",
        "1799-1800",
        "2000-2201",
        "1980-1989,",
        ",1980-1989",
        "1980-1989;1990-1999",
        "１９８０-１９８９",  # full-width digits
        "1980-1989 1990-1999",
        "0x7cc-0x7d5",
        "1980-1989'; drop table catalog_item; --",
    ],
)
def test_unusable_eras_are_refused(bad: str) -> None:
    with pytest.raises(FilterError):
        eras(bad)


@pytest.mark.parametrize(
    "hostile", ["<script>alert(1)</script>", "'; drop table x; --", "1234-9999x"]
)
def test_a_refused_era_is_never_repeated_back(hostile: str) -> None:
    with pytest.raises(FilterError) as error:
        eras(hostile)

    assert hostile not in str(error.value)


def test_too_many_eras_are_refused() -> None:
    many = ",".join(f"{1900 + 10 * i}-{1909 + 10 * i}" for i in range(MAX_ERA_RANGES))

    assert len(eras(many)) == MAX_ERA_RANGES
    with pytest.raises(FilterError, match="at most"):
        eras(many + ",2000-2009")


# --- what the era predicate keeps -------------------------------------------------------------


@pytest.mark.django_db
def test_an_era_keeps_years_inside_the_range_inclusive_and_drops_undated_rows() -> None:
    for year in (1979, 1980, 1985, 1989, 1990, None):
        add(f"Y{year}", MediaType.FILM, year)

    kept = Item.objects.filter(EraFilter().predicate(((1980, 1989),)))

    assert sorted(kept.values_list("title", flat=True)) == ["Y1980", "Y1985", "Y1989"]


@pytest.mark.django_db
def test_several_eras_are_or_ed_together() -> None:
    for year in (1975, 1985, 1995, 2005):
        add(f"Y{year}", MediaType.GAME, year)

    kept = Item.objects.filter(EraFilter().predicate(((1980, 1989), (2000, 2009))))

    assert sorted(kept.values_list("title", flat=True)) == ["Y1985", "Y2005"]


# --- media types -------------------------------------------------------------------------------


def test_media_types_default_when_the_parameter_is_absent() -> None:
    assert parse_media_types({}, (MediaType.FILM,)) == ("film",)
    assert parse_media_types({}, ALL_TYPES) == ALL_TYPES


def test_media_types_come_back_in_catalog_order_without_repeats() -> None:
    assert parse_media_types({"types": " Album , FILM,album"}, ("film",)) == ("film", "album")
    assert parse_media_types({"types": "album,game,film"}, ("film",)) == ALL_TYPES


@pytest.mark.parametrize("empty", ["", " ", ",", " , "])
def test_choosing_no_media_type_is_refused(empty: str) -> None:
    with pytest.raises(FilterError, match="at least one"):
        parse_media_types({"types": empty}, ALL_TYPES)


@pytest.mark.parametrize("bad", ["book", "film,book", "films", "film;game", "*"])
def test_an_unknown_media_type_is_refused_without_repeating_it(bad: str) -> None:
    with pytest.raises(FilterError) as error:
        parse_media_types({"types": bad}, ALL_TYPES)

    assert bad not in str(error.value)
    assert "film, game, album" in str(error.value)


# --- the registry ------------------------------------------------------------------------------


def test_the_era_filter_is_registered_and_applies_to_every_media_type() -> None:
    assert [f.name for f in FILTERS] == ["eras"]
    assert EraFilter().applies_to == {"film", "game", "album"}


def test_only_filters_with_a_value_are_active() -> None:
    assert parse_filters({}) == []
    (active,) = parse_filters({"eras": "1980-1989"})
    assert isinstance(active.filter, EraFilter)
    assert active.value == ((1980, 1989),)


def test_a_bad_value_fails_the_whole_parse() -> None:
    with pytest.raises(FilterError):
        parse_filters({"eras": "nope"})


def test_a_filter_applies_only_to_the_types_it_names() -> None:
    game_only = ActiveFilter(TitleStartsWith({"game"}), "Keep")

    assert str(predicate_for("game", [game_only])) == "(AND: ('title__startswith', 'Keep'))"
    assert predicate_for("film", [game_only]) == Q()
    assert predicate_for("album", [game_only]) == Q()


def test_a_filter_that_names_no_type_never_applies() -> None:
    nothing = ActiveFilter(TitleStartsWith(set()), "Keep")

    assert all(predicate_for(media_type, [nothing]) == Q() for media_type in ALL_TYPES)


def test_every_filter_that_applies_to_a_type_must_hold() -> None:
    era = ActiveFilter(EraFilter(), ((1980, 1989),))
    prefix = ActiveFilter(TitleStartsWith({"game"}), "Keep")

    assert "release_year__gte" in str(predicate_for("game", [era, prefix]))
    assert "title__startswith" in str(predicate_for("game", [era, prefix]))
    assert "title__startswith" not in str(predicate_for("film", [era, prefix]))


# --- retrieval: isolation across media types ---------------------------------------------------


@pytest.mark.django_db
def test_a_game_only_filter_removes_games_and_nothing_else() -> None:
    add("Keep film", MediaType.FILM, 2000)
    add("Drop film", MediaType.FILM, 2000)
    add("Keep game", MediaType.GAME, 2000)
    add("Drop game", MediaType.GAME, 2000)
    add("Drop album", MediaType.ALBUM, 2000)
    filters = [ActiveFilter(TitleStartsWith({"game"}), "Keep")]

    pools = retrieve_by_type(
        vec(1.0), media_types=ALL_TYPES, filters=filters, model=MODEL, dim=768, limit=10
    )

    titles = {t: sorted(h.item.title for h in hits) for t, hits in pools.items()}
    assert titles == {
        "film": ["Drop film", "Keep film"],
        "game": ["Keep game"],
        "album": ["Drop album"],
    }


@pytest.mark.django_db
def test_a_type_with_two_filters_keeps_only_what_passes_both() -> None:
    add("Keep 1985", MediaType.GAME, 1985)
    add("Keep 1975", MediaType.GAME, 1975)
    add("Drop 1985", MediaType.GAME, 1985)
    add("Drop 1975", MediaType.GAME, 1975)
    add("Keep film 1975", MediaType.FILM, 1975)
    add("Drop film 1985", MediaType.FILM, 1985)
    filters = [
        *parse_filters({"eras": "1980-1989"}),
        ActiveFilter(TitleStartsWith({"game"}), "Keep"),
    ]

    pools = retrieve_by_type(
        vec(1.0), media_types=("film", "game"), filters=filters, model=MODEL, dim=768, limit=10
    )

    assert [h.item.title for h in pools["game"]] == ["Keep 1985"]
    assert [h.item.title for h in pools["film"]] == ["Drop film 1985"]  # the era only


@pytest.mark.django_db
def test_an_era_applies_inside_each_types_own_pool() -> None:
    add("Old film", MediaType.FILM, 1975)
    add("New film", MediaType.FILM, 1985)
    add("Old game", MediaType.GAME, 1975)
    add("New game", MediaType.GAME, 1985)
    add("Undated album", MediaType.ALBUM, None)
    add("New album", MediaType.ALBUM, 1985)
    filters = parse_filters({"eras": "1980-1989"})

    pools = retrieve_by_type(
        vec(1.0), media_types=ALL_TYPES, filters=filters, model=MODEL, dim=768, limit=10
    )

    assert {t: [h.item.title for h in hits] for t, hits in pools.items()} == {
        "film": ["New film"],
        "game": ["New game"],
        "album": ["New album"],
    }


@pytest.mark.django_db
def test_without_an_era_undated_items_stay() -> None:
    add("Undated", MediaType.ALBUM, None)

    pools = retrieve_by_type(
        vec(1.0), media_types=ALL_TYPES, filters=[], model=MODEL, dim=768, limit=10
    )

    assert [h.item.title for h in pools["album"]] == ["Undated"]


@pytest.mark.django_db
def test_only_the_enabled_types_are_searched() -> None:
    add("A film", MediaType.FILM, 2000)
    add("A game", MediaType.GAME, 2000)

    pools = retrieve_by_type(
        vec(1.0), media_types=("game",), filters=[], model=MODEL, dim=768, limit=10
    )

    assert list(pools) == ["game"]


@pytest.mark.django_db
def test_each_pool_has_its_own_limit_and_a_busy_type_cannot_crowd_out_another() -> None:
    for i in range(6):
        add(f"Film {i}", MediaType.FILM, 2000, angle=0.0)
    add("Only game", MediaType.GAME, 2000, angle=5.0)

    pools = retrieve_by_type(
        vec(1.0), media_types=ALL_TYPES, filters=[], model=MODEL, dim=768, limit=3
    )

    assert len(pools["film"]) == 3
    assert [h.item.title for h in pools["game"]] == ["Only game"]
    assert pools["album"] == []


@pytest.mark.django_db
def test_retrieve_without_a_predicate_returns_every_item_of_the_type() -> None:
    add("A", MediaType.FILM, None)
    add("B", MediaType.FILM, 1990)

    hits = retrieve(vec(1.0), media_type="film", model=MODEL, dim=768, limit=10)

    assert sorted(h.item.title for h in hits) == ["A", "B"]
