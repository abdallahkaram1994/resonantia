"""catalog.detail: how a stored item's raw provider data becomes the detail page's fields."""

from datetime import UTC, datetime

import pytest

from catalog.detail import item_detail, item_details, item_scores
from catalog.models import Item, MediaType, Score

pytestmark = pytest.mark.django_db


FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def make(media_type: str, **details: object) -> Item:
    item = Item(media_type=media_type, title="Title", release_year=2001, summary="A summary.")
    item.details = details
    item.set_combined_text("Title")
    item.save()
    return item


# --- per-type details -----------------------------------------------------------------------


def test_a_films_details_are_its_genres_keywords_tagline_and_runtime() -> None:
    item = make(
        MediaType.FILM,
        genres=["Drama", "Noir"],
        keywords=["rain"],
        tagline="Every city has one.",
        runtime=104,
        original_title="ignored",
    )

    assert item_details(item) == {
        "genres": ["Drama", "Noir"],
        "keywords": ["rain"],
        "tagline": "Every city has one.",
        "runtime": 104,
    }


def test_a_games_details_are_its_genres_themes_and_keywords() -> None:
    item = make(MediaType.GAME, genres=["Adventure"], themes=["Open world"], keywords=["survival"])

    assert item_details(item) == {
        "genres": ["Adventure"],
        "themes": ["Open world"],
        "keywords": ["survival"],
    }


def test_an_albums_details_are_its_artist_and_tags() -> None:
    item = make(MediaType.ALBUM, artist="Band A", tags=["indie", "night drive"])

    details = item_details(item)

    assert details["artist"] == "Band A"
    assert details["tags"] == ["indie", "night drive"]


def test_an_albums_wikipedia_credit_is_included_when_present() -> None:
    item = make(
        MediaType.ALBUM,
        artist="Band A",
        wikipedia={"title": "Studio One", "url": "https://en.wikipedia.org/wiki/Studio_One"},
    )

    assert item_details(item)["wikipedia"] == {
        "title": "Studio One",
        "url": "https://en.wikipedia.org/wiki/Studio_One",
    }


@pytest.mark.parametrize(
    "wikipedia", [None, {}, {"title": "Studio One"}, {"url": "https://en.wikipedia.org/x"}, "x"]
)
def test_an_albums_wikipedia_credit_is_null_when_incomplete_or_missing(wikipedia: object) -> None:
    item = make(MediaType.ALBUM, artist="Band A", wikipedia=wikipedia)

    assert item_details(item)["wikipedia"] is None


def test_missing_fields_become_empty_not_a_crash() -> None:
    assert item_details(make(MediaType.FILM)) == {
        "genres": [],
        "keywords": [],
        "tagline": "",
        "runtime": None,
    }
    assert item_details(make(MediaType.GAME)) == {"genres": [], "themes": [], "keywords": []}
    assert item_details(make(MediaType.ALBUM)) == {"artist": "", "tags": [], "wikipedia": None}


def test_internal_ids_are_never_exposed() -> None:
    item = make(
        MediaType.ALBUM,
        artist="Band A",
        release_group_mbid="11111111-1111-1111-1111-111111111111",
        release_mbid="22222222-2222-2222-2222-222222222222",
        lastfm={"listeners": 90000, "url": "https://last.fm/x"},
    )

    details = item_details(item)

    assert "release_group_mbid" not in details
    assert "release_mbid" not in details
    assert "lastfm" not in details


# --- scores ------------------------------------------------------------------------------------


def test_scores_are_display_fields_with_their_source_and_vote_count() -> None:
    item = make(MediaType.FILM)
    Score.objects.create(
        item=item, source="tmdb", value=7.4, vote_count=1500, fetched_at=FETCHED_AT
    )

    assert item_scores(item) == [{"source": "tmdb", "value": 7.4, "vote_count": 1500}]


def test_an_album_has_no_scores_with_no_special_casing() -> None:
    assert item_scores(make(MediaType.ALBUM)) == []


def test_several_scores_are_all_returned() -> None:
    item = make(MediaType.FILM)
    Score.objects.create(
        item=item, source="tmdb", value=7.4, vote_count=1500, fetched_at=FETCHED_AT
    )
    Score.objects.create(
        item=item, source="omdb-rt", value=88, vote_count=None, fetched_at=FETCHED_AT
    )

    assert {s["source"] for s in item_scores(item)} == {"tmdb", "omdb-rt"}


# --- the whole detail record ---------------------------------------------------------------


def test_item_detail_has_the_common_display_fields_plus_details_and_scores() -> None:
    item = make(MediaType.GAME, genres=["Adventure"])
    item.cover_url = "https://images.igdb.com/x.jpg"
    item.save()
    Score.objects.create(
        item=item, source="igdb", value=84.2, vote_count=1500, fetched_at=FETCHED_AT
    )

    detail = item_detail(item)

    assert detail == {
        "id": item.id,
        "media_type": "game",
        "title": "Title",
        "release_year": 2001,
        "cover_url": "https://images.igdb.com/x.jpg",
        "summary": "A summary.",
        "details": {"genres": ["Adventure"], "themes": [], "keywords": []},
        "scores": [{"source": "igdb", "value": 84.2, "vote_count": 1500}],
    }
