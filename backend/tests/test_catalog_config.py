import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from catalog.sources.factory import get_film_source, get_game_source
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
