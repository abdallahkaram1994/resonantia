"""IGDB adapter tests. The two error fixtures are real responses to fake credentials. The games
are invented, in the response shape verified against the live API (see fixtures/igdb/README.md)."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceRequestError, SourceUnavailable
from catalog.sources.igdb import API_URL, TOKEN_URL, IgdbGameSource
from tests.helpers import CountingThrottle, FakeClock, ScriptedTransport, fixture_bytes

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret-not-real"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def fixture(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, fixture_bytes(f"igdb/{name}.json"))


def inline(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload).encode())


def main_games() -> list[dict]:
    return json.loads(fixture_bytes("igdb/games_main.json"))


def paged(pages: dict[int, list]):
    """Handler that serves the token, then the page whose offset the query asks for."""

    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if url == TOKEN_URL:
            return fixture("token")
        offset = int(re.search(r"offset (\d+);", body).group(1))
        return inline(pages.get(offset, []))

    return handler


def make_source(handler=None, **overrides: object):
    transport = ScriptedTransport(handler or paged({0: main_games()}))
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "throttle": throttle,
        "cover_size": "t_cover_big",
        "min_rating_count": 75,
        "mid_tail_min_rating_count": 25,
        "max_keywords": 10,
        "transport": transport,
        "sleep": clock.sleep,
        "clock": lambda: NOW,
    }
    kwargs.update(overrides)
    return IgdbGameSource(**kwargs), transport, throttle  # type: ignore[arg-type]


def api_calls(transport: ScriptedTransport) -> list[dict]:
    return [c for c in transport.calls if c["url"] == API_URL]


def token_calls(transport: ScriptedTransport) -> list[dict]:
    return [c for c in transport.calls if c["url"] == TOKEN_URL]


def test_the_token_is_requested_once_with_credentials_in_the_body_not_the_url() -> None:
    pages = {
        0: [{"id": i, "name": f"G{i}"} for i in range(100)],
        100: [{"id": 500, "name": "Last"}],
    }
    source, transport, _ = make_source(paged(pages))

    list(source.popular())

    [token_call] = token_calls(transport)
    assert token_call["method"] == "POST"
    assert token_call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    form = parse_qs(token_call["body"])
    assert form == {
        "client_id": [CLIENT_ID],
        "client_secret": [CLIENT_SECRET],
        "grant_type": ["client_credentials"],
    }
    assert CLIENT_SECRET not in token_call["url"]
    assert len(api_calls(transport)) == 2  # two pages, still one token


def test_the_games_query_asks_for_popular_main_games_most_rated_first() -> None:
    source, transport, _ = make_source()

    list(source.popular())

    call = api_calls(transport)[0]
    assert call["method"] == "POST"
    assert call["headers"]["Client-ID"] == CLIENT_ID
    assert call["headers"]["Authorization"] == "Bearer fixture-token-not-real"
    assert call["headers"]["Content-Type"] == "text/plain"
    body = call["body"]
    assert "game_type = 0" in body
    assert "version_parent = null" in body
    assert "total_rating_count >= 75" in body
    assert "sort total_rating_count desc" in body
    assert "limit 100; offset 0;" in body
    assert "cover.image_id" in body
    assert CLIENT_SECRET not in body


def test_the_mid_tail_asks_for_the_band_below_the_popularity_threshold() -> None:
    source, transport, _ = make_source()

    list(source.mid_tail())

    body = api_calls(transport)[0]["body"]
    assert "total_rating_count >= 25 & total_rating_count < 75" in body
    assert "game_type = 0" in body


def test_a_full_page_leads_to_the_next_offset_and_a_short_page_ends_the_walk() -> None:
    pages = {
        0: [{"id": i, "name": f"G{i}"} for i in range(100)],
        100: [{"id": 100 + i, "name": f"G{100 + i}"} for i in range(30)],
    }
    source, transport, _ = make_source(paged(pages))

    records = list(source.popular())

    assert len(records) == 130
    offsets = [re.search(r"offset (\d+);", c["body"]).group(1) for c in api_calls(transport)]
    assert offsets == ["0", "100"]


def test_games_are_fetched_lazily() -> None:
    pages = {0: [{"id": i, "name": f"G{i}"} for i in range(100)]}
    source, transport, _ = make_source(paged(pages))

    next(source.popular())

    assert len(token_calls(transport)) == 1
    assert len(api_calls(transport)) == 1


def test_every_api_call_is_throttled() -> None:
    pages = {0: [{"id": i, "name": f"G{i}"} for i in range(100)], 100: []}
    source, transport, throttle = make_source(paged(pages))

    list(source.popular())

    assert throttle.waits == len(api_calls(transport)) == 2


def test_a_full_game_is_parsed() -> None:
    source, _, _ = make_source()

    game = next(source.popular())

    assert (game.media_type, game.source, game.source_id) == ("game", "igdb", "9001")
    assert game.title == "Neon Harbor"
    assert game.release_year == 2013
    assert game.summary.startswith("A courier races")
    assert game.genres == ("Shooter", "Adventure")
    assert game.keywords[:2] == ("Action", "Fantasy")  # themes first
    assert game.cover_url == "https://images.igdb.com/igdb/image/upload/t_cover_big/co9001.jpg"
    assert game.score is not None
    assert (game.score.source, game.score.vote_count) == ("igdb", 5982)
    assert game.score.value == pytest.approx(88.8929, abs=1e-3)
    assert game.fetched_at == NOW
    assert game.is_embeddable is True
    assert game.details["themes"] == ["Action", "Fantasy"]


def test_keywords_are_capped_and_never_repeat_a_theme() -> None:
    rows = main_games()
    rows[0]["keywords"].insert(0, {"id": 99, "name": "Action"})  # repeats a theme
    source, _, _ = make_source(paged({0: rows}), max_keywords=3)

    game = next(source.popular())

    assert game.keywords == ("Action", "Fantasy", "aliens", "helicopter")
    assert game.details["keywords"] == ["Action", "aliens", "helicopter"]


def test_zero_max_keywords_keeps_only_themes() -> None:
    source, _, _ = make_source(max_keywords=0)

    game = next(source.popular())

    assert game.keywords == ("Action", "Fantasy")


def test_edge_games_are_parsed_without_crashing() -> None:
    source, _, _ = make_source()

    games = {g.source_id: g for g in source.popular()}

    lighthouse = games["9002"]
    assert lighthouse.release_year is None
    assert lighthouse.cover_url == ""
    assert lighthouse.score is None
    assert lighthouse.is_embeddable is True  # a summary, a genre and a theme are enough
    shell = games["9003"]
    assert shell.summary == ""
    assert shell.genres == () and shell.keywords == ()
    assert shell.is_embeddable is False


def test_the_cover_size_comes_from_config() -> None:
    source, _, _ = make_source(cover_size="t_cover_small")

    assert next(source.popular()).cover_url.endswith("/t_cover_small/co9001.jpg")


@pytest.mark.parametrize("size", ["", "cover_big", "t_cover/../x", "T_COVER", "t_"])
def test_a_cover_size_that_could_alter_the_url_is_rejected(size: str) -> None:
    with pytest.raises(ValueError):
        make_source(cover_size=size)


def test_hostile_field_values_are_neutralised() -> None:
    hostile = {
        "id": 1,
        "name": "T" * 1000,
        "summary": 123,
        "first_release_date": "1379376000",
        "genres": "Shooter",
        "themes": [None, 5, {"name": 7}],
        "keywords": {"name": "x"},
        "cover": {"image_id": "../../evil"},
        "total_rating": "88",
        "total_rating_count": True,
    }
    source, _, _ = make_source(paged({0: [hostile]}))

    game = next(source.popular())

    assert len(game.title) == 500
    assert game.summary == ""
    assert game.release_year is None
    assert game.genres == () and game.keywords == ()
    assert game.cover_url == ""
    assert game.score is None


@pytest.mark.parametrize("image_id", ["", "AB", "a" * 41, "co 1", "co1/x", "co1.jpg", None, 7])
def test_only_well_formed_image_ids_become_cover_urls(image_id: object) -> None:
    rows = [{"id": 1, "name": "G", "cover": {"image_id": image_id}}]
    source, _, _ = make_source(paged({0: rows}))

    assert next(source.popular()).cover_url == ""


@pytest.mark.parametrize(
    ("timestamp", "year"),
    [
        (1379376000, 2013),
        (-1_000_000_000, None),
        (10**15, None),
        (-(10**12), None),
        (None, None),
        (1.5, None),
    ],
)
def test_release_years_come_from_unix_timestamps(timestamp: object, year: int | None) -> None:
    rows = [{"id": 1, "name": "G", "first_release_date": timestamp}]
    source, _, _ = make_source(paged({0: rows}))

    assert next(source.popular()).release_year == year


def test_rows_without_an_id_or_a_name_are_dropped() -> None:
    rows = [
        {"name": "No id"},
        {"id": "2", "name": "String id"},
        {"id": 3},
        {"id": 4, "name": "  "},
        None,
        "x",
    ]
    source, _, _ = make_source(paged({0: rows}))

    assert list(source.popular()) == []


def test_rejected_credentials_are_a_request_error_that_does_not_leak_them() -> None:
    source, _, _ = make_source(lambda m, u, h, b: fixture("error_token_invalid_client", 400))

    with pytest.raises(SourceRequestError) as excinfo:
        next(source.popular())

    message = str(excinfo.value)
    assert "HTTP 400" in message
    assert "TWITCH_CLIENT_ID" in message
    assert CLIENT_SECRET not in message and CLIENT_ID not in message


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(503, {}, b"{}"),
        HttpResponse(200, {}, b"<html>oops</html>"),
        inline({"no_token": True}),
        inline([]),
        inline({"access_token": ""}),
    ],
)
def test_a_failed_or_unusable_token_response_is_unavailable(response: HttpResponse) -> None:
    source, _, _ = make_source(lambda m, u, h, b: response, retry=RetryPolicy(max_retries=0))

    with pytest.raises(SourceUnavailable):
        next(source.popular())


def test_a_network_failure_getting_the_token_is_unavailable() -> None:
    source, _, _ = make_source(lambda m, u, h, b: NetworkError("URLError"))

    with pytest.raises(SourceUnavailable):
        next(source.popular())


def test_an_expired_token_is_replaced_once_and_the_request_retried() -> None:
    api_attempts = []

    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if url == TOKEN_URL:
            return fixture("token")
        api_attempts.append(1)
        if len(api_attempts) == 1:
            return fixture("error_unauthorized", 401)
        return inline(main_games())

    source, transport, _ = make_source(handler)

    games = list(source.popular())

    assert len(games) == 3
    assert len(token_calls(transport)) == 2
    assert len(api_calls(transport)) == 2


def test_a_token_that_is_still_rejected_after_a_refresh_is_a_request_error() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        return fixture("token") if url == TOKEN_URL else fixture("error_unauthorized", 401)

    source, transport, _ = make_source(handler)

    with pytest.raises(SourceRequestError) as excinfo:
        next(source.popular())

    assert "HTTP 401" in str(excinfo.value)
    assert "Check the Twitch credentials" in str(excinfo.value)
    assert len(token_calls(transport)) == 2
    assert len(api_calls(transport)) == 2  # not an endless loop


def test_a_bad_query_shows_igdbs_short_message() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if url == TOKEN_URL:
            return fixture("token")
        return inline({"message": "Invalid Field: nope"}, 400)

    source, _, _ = make_source(handler)

    with pytest.raises(SourceRequestError, match="HTTP 400: Invalid Field: nope"):
        next(source.popular())


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limiting_and_outages_are_unavailable_after_retries(status: int) -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        return fixture("token") if url == TOKEN_URL else HttpResponse(status, {}, b"{}")

    source, transport, _ = make_source(handler, retry=RetryPolicy(max_retries=2))

    with pytest.raises(SourceUnavailable):
        next(source.popular())

    assert len(api_calls(transport)) == 3


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(200, {}, b"<html>bad gateway</html>"),
        inline({"unexpected": "object"}),
        inline("text"),
    ],
)
def test_unusable_api_responses_are_unavailable(response: HttpResponse) -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        return fixture("token") if url == TOKEN_URL else response

    source, _, _ = make_source(handler)

    with pytest.raises(SourceUnavailable):
        next(source.popular())


def test_secrets_are_not_in_the_repr() -> None:
    source, _, _ = make_source()

    assert CLIENT_SECRET not in repr(source)
    assert CLIENT_ID not in repr(source)
