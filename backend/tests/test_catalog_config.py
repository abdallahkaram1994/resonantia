import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from catalog.sources.albums import DATA_DIR, AlbumSource, load_lines
from catalog.sources.factory import get_album_source, get_film_source, get_game_source
from catalog.sources.igdb import IgdbGameSource
from catalog.sources.tmdb import TmdbFilmSource
from tests.helpers import load_settings_value


def check_ids() -> list[str]:
    return [error.id for error in run_checks()]


def test_default_vote_thresholds_pass_the_system_checks() -> None:
    assert "catalog.E002" not in check_ids()


@pytest.mark.parametrize(("mid_tail", "popular"), [(1000, 1000), (1500, 1000)])
def test_mid_tail_band_must_sit_below_the_popularity_threshold(mid_tail: int, popular: int) -> None:
    with override_settings(FILM_MID_TAIL_MIN_VOTE_COUNT=mid_tail, FILM_MIN_VOTE_COUNT=popular):
        assert "catalog.E002" in check_ids()


@override_settings(TMDB_READ_ACCESS_TOKEN="")
def test_film_source_needs_a_token() -> None:
    with pytest.raises(ImproperlyConfigured, match="TMDB_READ_ACCESS_TOKEN"):
        get_film_source()


@override_settings(TMDB_READ_ACCESS_TOKEN="token")
def test_film_source_is_built_from_settings() -> None:
    assert isinstance(get_film_source(), TmdbFilmSource)


def test_film_settings_have_sensible_defaults() -> None:
    expected = {
        "TMDB_REQUESTS_PER_SECOND": "20",
        "TMDB_MAX_CACHE_DAYS": "150",
        "FILM_MIN_VOTE_COUNT": "1000",
        "FILM_MID_TAIL_MIN_VOTE_COUNT": "200",
        "MID_TAIL_PERCENT": "10",
        "CATALOG_TARGET_PER_TYPE": "2000",
        "INGEST_LIMIT": "0",
        "TMDB_IMAGE_BASE_URL": "https://image.tmdb.org/t/p/w342",
    }
    for name, value in expected.items():
        result = load_settings_value(name, {})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == value, name


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("MID_TAIL_PERCENT", "101"),
        ("MID_TAIL_PERCENT", "-1"),
        ("TMDB_REQUESTS_PER_SECOND", "0"),
        ("CATALOG_TARGET_PER_TYPE", "lots"),
        ("INGEST_LIMIT", "-5"),
    ],
)
def test_settings_reject_out_of_range_values(name: str, bad: str) -> None:
    result = load_settings_value(name, {name: bad})

    assert result.returncode != 0
    assert name in result.stderr


def test_zero_is_allowed_for_the_ingest_limit_and_mid_tail_percent() -> None:
    for name in ("INGEST_LIMIT", "MID_TAIL_PERCENT"):
        result = load_settings_value(name, {name: "0"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0"


@pytest.mark.parametrize(("mid_tail", "popular"), [(75, 75), (100, 75)])
def test_game_mid_tail_band_must_sit_below_the_popularity_threshold(
    mid_tail: int, popular: int
) -> None:
    with override_settings(GAME_MID_TAIL_MIN_RATING_COUNT=mid_tail, GAME_MIN_RATING_COUNT=popular):
        assert "catalog.E003" in check_ids()


def test_default_game_thresholds_pass_the_system_checks() -> None:
    assert "catalog.E003" not in check_ids()


@pytest.mark.parametrize(
    ("client_id", "client_secret"),
    [("", ""), ("id", ""), ("", "secret")],
)
def test_game_source_needs_both_twitch_credentials(client_id: str, client_secret: str) -> None:
    with (
        override_settings(TWITCH_CLIENT_ID=client_id, TWITCH_CLIENT_SECRET=client_secret),
        pytest.raises(ImproperlyConfigured, match="TWITCH_CLIENT_ID"),
    ):
        get_game_source()


@override_settings(TWITCH_CLIENT_ID="id", TWITCH_CLIENT_SECRET="secret")
def test_game_source_is_built_from_settings() -> None:
    assert isinstance(get_game_source(), IgdbGameSource)


def test_game_settings_have_sensible_defaults() -> None:
    expected = {
        "IGDB_REQUESTS_PER_SECOND": "3",
        "IGDB_COVER_SIZE": "t_cover_big",
        "GAME_MIN_RATING_COUNT": "75",
        "GAME_MID_TAIL_MIN_RATING_COUNT": "25",
        "GAME_MAX_KEYWORDS": "10",
    }
    for name, value in expected.items():
        result = load_settings_value(name, {})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == value, name


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("IGDB_REQUESTS_PER_SECOND", "0"),
        ("GAME_MIN_RATING_COUNT", "0"),
        ("GAME_MAX_KEYWORDS", "-1"),
        ("GAME_MAX_KEYWORDS", "many"),
    ],
)
def test_game_settings_reject_out_of_range_values(name: str, bad: str) -> None:
    result = load_settings_value(name, {name: bad})

    assert result.returncode != 0
    assert name in result.stderr


def test_zero_keywords_is_allowed() -> None:
    result = load_settings_value("GAME_MAX_KEYWORDS", {"GAME_MAX_KEYWORDS": "0"})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


# --- album catalog settings -----------------------------------------------------------------


@pytest.mark.parametrize(("mid_tail", "popular"), [(50000, 50000), (60000, 50000)])
def test_album_mid_tail_band_must_sit_below_the_popularity_threshold(
    mid_tail: int, popular: int
) -> None:
    with override_settings(ALBUM_MID_TAIL_MIN_LISTENERS=mid_tail, ALBUM_MIN_LISTENERS=popular):
        assert "catalog.E004" in check_ids()


def test_default_album_thresholds_pass_the_system_checks() -> None:
    assert "catalog.E004" not in check_ids()


def test_album_settings_have_sensible_defaults() -> None:
    expected = {
        "LASTFM_REQUESTS_PER_SECOND": "2",
        "ALBUM_MIN_LISTENERS": "50000",
        "ALBUM_MID_TAIL_MIN_LISTENERS": "10000",
        "ALBUM_MAX_TAGS": "10",
        "ALBUM_COVER_SIZE": "500",
        "ALBUM_BATCH_SIZE": "20",
        "MUSICBRAINZ_MIN_INTERVAL_SECONDS": "1.1",
        "WIKIMEDIA_REQUESTS_PER_SECOND": "1",
        "COVERART_REQUESTS_PER_SECOND": "4",
        "ALBUM_MID_TAIL_START_PAGE": "20",
        "ALBUM_MID_TAIL_MAX_SCAN": "1000",
    }
    for name, value in expected.items():
        result = load_settings_value(name, {})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == value, name


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("ALBUM_COVER_SIZE", "300"),
        ("ALBUM_COVER_SIZE", "big"),
        ("ALBUM_BATCH_SIZE", "21"),
        ("ALBUM_BATCH_SIZE", "0"),
        ("ALBUM_MAX_TAGS", "0"),
        ("LASTFM_REQUESTS_PER_SECOND", "0"),
        ("COVERART_REQUESTS_PER_SECOND", "-1"),
        ("ALBUM_MID_TAIL_START_PAGE", "0"),
        ("ALBUM_MID_TAIL_MAX_SCAN", "0"),
        ("MUSICBRAINZ_MIN_INTERVAL_SECONDS", "0.5"),
        ("MUSICBRAINZ_MIN_INTERVAL_SECONDS", "fast"),
    ],
)
def test_album_settings_reject_out_of_range_values(name: str, bad: str) -> None:
    result = load_settings_value(name, {name: bad})

    assert result.returncode != 0
    assert name in result.stderr


@pytest.mark.parametrize("size", ["250", "500", "1200"])
def test_the_supported_cover_sizes_are_accepted(size: str) -> None:
    result = load_settings_value("ALBUM_COVER_SIZE", {"ALBUM_COVER_SIZE": size})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == size


def test_musicbrainz_cannot_be_configured_faster_than_it_allows() -> None:
    ok = load_settings_value(
        "MUSICBRAINZ_MIN_INTERVAL_SECONDS", {"MUSICBRAINZ_MIN_INTERVAL_SECONDS": "1.0"}
    )

    assert ok.returncode == 0 and ok.stdout.strip() == "1.0"


@pytest.mark.parametrize(
    ("api_key", "contact", "message"),
    [
        ("", "me@example.com", "LASTFM_API_KEY"),
        ("key", "", "CONTACT_EMAIL is not set"),
        ("key", "no way to reach me", "CONTACT_EMAIL"),
        ("key", "me@example.com\r\nX-Injected: 1", "CONTACT_EMAIL"),
    ],
)
def test_album_source_needs_a_key_and_a_usable_contact(
    api_key: str, contact: str, message: str
) -> None:
    with (
        override_settings(LASTFM_API_KEY=api_key, CONTACT_EMAIL=contact),
        pytest.raises(ImproperlyConfigured, match=message),
    ):
        get_album_source()


@override_settings(LASTFM_API_KEY="key", CONTACT_EMAIL="https://github.com/someone/resonantia")
def test_album_source_is_built_from_settings() -> None:
    assert isinstance(get_album_source(), AlbumSource)


def test_the_shipped_tag_list_is_a_wide_clean_set_of_genres() -> None:
    tags = load_lines(DATA_DIR / "lastfm_tags.txt")

    assert len(tags) >= 50
    assert len({t.lower() for t in tags}) == len(tags)
    assert all(t == t.strip() and t and not t.startswith("#") for t in tags)
    assert {"rock", "electronic", "jazz", "ambient", "hip-hop"} <= set(tags)


def test_the_shipped_blocklist_covers_listener_tags() -> None:
    blocked = {t.lower() for t in load_lines(DATA_DIR / "lastfm_tag_blocklist.txt")}

    assert {"seen live", "favorites", "favourites", "albums i own"} <= blocked


def test_list_files_ignore_comments_blanks_and_repeats(tmp_path) -> None:
    path = tmp_path / "tags.txt"
    path.write_text("# comment\nRock\n\n  jazz  \nrock\n# another\nJAZZ\nfolk\n", encoding="utf-8")

    assert load_lines(path) == ["Rock", "jazz", "folk"]


@override_settings(
    LASTFM_API_KEY="key",
    CONTACT_EMAIL="https://github.com/someone/resonantia",
    ALBUM_MID_TAIL_START_PAGE=6,
    ALBUM_MID_TAIL_MAX_SCAN=77,
)
def test_the_album_source_gets_its_mid_tail_settings_and_a_progress_callback() -> None:
    messages: list[str] = []

    source = get_album_source(heartbeat=messages.append)

    assert source._mid_tail_start_page == 6  # type: ignore[attr-defined]
    assert source._mid_tail_max_scan == 77  # type: ignore[attr-defined]
    source._say("hello")  # type: ignore[attr-defined]
    assert messages == ["hello"]


def test_search_layout_settings_have_sensible_defaults() -> None:
    expected = {
        "SEARCH_RESULT_LIMIT": "15",
        "SEARCH_GROUP_LIMIT": "10",
        "SEARCH_CANDIDATES_PER_TYPE": "50",
        "SEARCH_BLEND_MIN_SLOTS": "2",
    }
    for name, value in expected.items():
        result = load_settings_value(name, {})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == value, name


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("SEARCH_RESULT_LIMIT", "0"),
        ("SEARCH_GROUP_LIMIT", "0"),
        ("SEARCH_CANDIDATES_PER_TYPE", "0"),
        ("SEARCH_BLEND_MIN_SLOTS", "-1"),
        ("SEARCH_GROUP_LIMIT", "many"),
    ],
)
def test_search_layout_settings_reject_bad_values(name: str, bad: str) -> None:
    result = load_settings_value(name, {name: bad})

    assert result.returncode != 0
    assert name in result.stderr


def test_the_blend_reservation_can_be_switched_off() -> None:
    result = load_settings_value("SEARCH_BLEND_MIN_SLOTS", {"SEARCH_BLEND_MIN_SLOTS": "0"})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def test_the_default_candidate_pool_covers_what_is_shown() -> None:
    assert "catalog.E005" not in check_ids()


@pytest.mark.parametrize(
    ("candidates", "results", "group"),
    [(14, 15, 10), (9, 5, 10), (10, 15, 10)],
)
def test_the_candidate_pool_must_cover_the_lists_shown(
    candidates: int, results: int, group: int
) -> None:
    with override_settings(
        SEARCH_CANDIDATES_PER_TYPE=candidates,
        SEARCH_RESULT_LIMIT=results,
        SEARCH_GROUP_LIMIT=group,
    ):
        assert "catalog.E005" in check_ids()


def test_a_pool_exactly_as_large_as_the_lists_is_fine() -> None:
    with override_settings(
        SEARCH_CANDIDATES_PER_TYPE=15, SEARCH_RESULT_LIMIT=15, SEARCH_GROUP_LIMIT=10
    ):
        assert "catalog.E005" not in check_ids()


def test_item_similar_limit_has_a_sensible_default() -> None:
    result = load_settings_value("ITEM_SIMILAR_LIMIT", {})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "12"


def test_item_similar_limit_rejects_bad_values() -> None:
    result = load_settings_value("ITEM_SIMILAR_LIMIT", {"ITEM_SIMILAR_LIMIT": "0"})

    assert result.returncode != 0
    assert "ITEM_SIMILAR_LIMIT" in result.stderr
