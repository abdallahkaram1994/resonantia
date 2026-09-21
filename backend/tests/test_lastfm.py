"""Last.fm client tests, with invented records in Last.fm's JSON shape (see
tests/fixtures/lastfm/README.md). Not yet checked against the live API."""

import json
from urllib.parse import parse_qs

import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceRequestError, SourceUnavailable
from catalog.sources.lastfm import LastFmClient
from tests.helpers import CountingThrottle, FakeClock, ScriptedTransport, fixture_bytes

AGENT = "Resonantia/0.1 (test@example.com)"
API_KEY = "test-lastfm-key-not-real"
RELEASE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def fixture(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, fixture_bytes(f"lastfm/{name}.json"))


def inline(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload).encode())


def make_client(outcome, **overrides: object):
    handler = outcome if callable(outcome) else (lambda method, url, headers, body: outcome)
    transport = ScriptedTransport(handler)
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "api_key": API_KEY,
        "user_agent": AGENT,
        "throttle": throttle,
        "blocklist": ["seen live", "Favourites"],
        "max_tags": 10,
        "transport": transport,
        "sleep": clock.sleep,
    }
    kwargs.update(overrides)
    return LastFmClient(**kwargs), transport, throttle  # type: ignore[arg-type]


def form_of(call: dict) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(call["body"]).items()}


def test_top_albums_sends_a_post_with_the_key_in_the_body_not_the_url() -> None:
    client, transport, throttle = make_client(fixture("top_albums_page1"))

    client.top_albums("indie rock", 3)

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://ws.audioscrobbler.com/2.0/"
    assert API_KEY not in call["url"]
    assert call["headers"]["User-Agent"] == AGENT
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert form_of(call) == {
        "method": "tag.gettopalbums",
        "tag": "indie rock",
        "page": "3",
        "limit": "50",
        "api_key": API_KEY,
        "format": "json",
    }
    assert throttle.waits == 1


def test_top_albums_are_parsed_and_an_album_without_an_id_keeps_none() -> None:
    client, _, _ = make_client(fixture("top_albums_page1"))

    albums = client.top_albums("rock", 1)

    assert [(a.name, a.artist, a.mbid) for a in albums] == [
        ("The Rainy Hour", "Fixture Band", "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"),
        ("No Id Album", "Other Artist", None),
        ("Second Record", "Fixture Band", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"),
    ]
    assert albums[0].url == "https://www.last.fm/music/Fixture+Band/The+Rainy+Hour"


def test_a_single_result_arrives_as_an_object_and_is_still_read() -> None:
    client, _, _ = make_client(fixture("top_albums_single"))

    albums = client.top_albums("rare", 1)

    assert [(a.name, a.artist) for a in albums] == [("Only One", "Lone Artist")]


def test_an_empty_page_is_an_empty_list() -> None:
    client, _, _ = make_client(fixture("top_albums_empty"))

    assert client.top_albums("rock", 999) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"albums": "nope"},
        {"albums": {"album": "nope"}},
        {"albums": {"album": [None, 3, "x", {"name": ""}, {"mbid": "x"}]}},
        {},
    ],
)
def test_odd_top_album_shapes_give_no_albums_instead_of_crashing(payload: object) -> None:
    client, _, _ = make_client(inline(payload))

    assert client.top_albums("rock", 1) == []


def test_a_malformed_or_hostile_mbid_is_treated_as_missing() -> None:
    body = {"albums": {"album": [{"name": "A", "mbid": "../../etc", "artist": "X"}]}}
    client, _, _ = make_client(inline(body))

    assert client.top_albums("rock", 1)[0].mbid is None


def test_album_info_asks_by_release_id_only() -> None:
    client, transport, _ = make_client(fixture("album_info_popular"))

    client.album_info(RELEASE.upper())

    assert form_of(transport.calls[0]) == {
        "method": "album.getinfo",
        "mbid": RELEASE,
        "api_key": API_KEY,
        "format": "json",
    }


@pytest.mark.parametrize("bad", ["", "nope", "../x"])
def test_a_malformed_id_is_never_sent_to_lastfm(bad: str) -> None:
    client, transport, _ = make_client(fixture("album_info_popular"))

    assert client.album_info(bad) is None
    assert transport.calls == []


def test_tags_drop_listener_tags_names_and_repeats() -> None:
    client, _, _ = make_client(fixture("album_info_popular"))

    info = client.album_info(RELEASE)

    assert info is not None
    # Dropped: "seen live" (blocklist), "fixture band" (the artist), "the rainy hour" (the
    # album), and the second "melancholic" (a repeat ignoring case).
    assert info.tags == ("alternative rock", "Melancholic", "night drive")
    assert info.listeners == 250000
    assert info.url == "https://www.last.fm/music/Fixture+Band/The+Rainy+Hour"


def test_tags_are_capped_in_lastfms_order() -> None:
    tags = [{"name": f"tag{i}"} for i in range(30)]
    client, _, _ = make_client(
        inline({"album": {"name": "A", "artist": "B", "listeners": "5", "tags": {"tag": tags}}}),
        max_tags=4,
    )

    assert client.album_info(RELEASE).tags == ("tag0", "tag1", "tag2", "tag3")  # type: ignore[union-attr]


def test_the_blocklist_ignores_case_and_surrounding_spaces() -> None:
    tags = [{"name": "SEEN LIVE"}, {"name": "favourites"}, {"name": "shoegaze"}]
    client, _, _ = make_client(
        inline({"album": {"name": "A", "artist": "B", "tags": {"tag": tags}}}),
        blocklist=[" Seen Live ", "FAVOURITES"],
    )

    assert client.album_info(RELEASE).tags == ("shoegaze",)  # type: ignore[union-attr]


def test_over_long_and_junk_tags_are_dropped() -> None:
    tags = [{"name": "x" * 51}, {"name": ""}, {"name": 7}, None, "plain", {"name": "ok"}]
    client, _, _ = make_client(
        inline({"album": {"name": "A", "artist": "B", "tags": {"tag": tags}}})
    )

    assert client.album_info(RELEASE).tags == ("plain", "ok")  # type: ignore[union-attr]


def test_a_single_tag_arrives_as_an_object_and_is_still_read() -> None:
    client, _, _ = make_client(fixture("album_info_single_tag"))

    info = client.album_info(RELEASE)

    assert info is not None and info.tags == ("ambient",) and info.listeners == 1200


def test_no_tags_arrive_as_an_empty_string() -> None:
    client, _, _ = make_client(fixture("album_info_no_tags"))

    info = client.album_info(RELEASE)

    assert info is not None
    assert info.tags == ()
    assert info.listeners == 80000


@pytest.mark.parametrize(
    ("listeners", "expected"),
    [
        ("250000", 250000),
        (250000, 250000),
        (" 5 ", 5),
        ("", None),
        ("many", None),
        ("-5", None),
        (None, None),
        (True, None),
        (12.5, None),
    ],
)
def test_listener_counts_are_read_from_strings_or_numbers(
    listeners: object, expected: object
) -> None:
    client, _, _ = make_client(
        inline({"album": {"name": "A", "artist": "B", "listeners": listeners}})
    )

    assert client.album_info(RELEASE).listeners == expected  # type: ignore[union-attr]


def test_an_album_lastfm_does_not_know_is_none_not_an_error() -> None:
    client, _, _ = make_client(fixture("error_not_found"))

    assert client.album_info(RELEASE) is None


def test_lastfm_error_bodies_are_read_whatever_the_http_status() -> None:
    client, _, _ = make_client(fixture("error_not_found", 404))

    assert client.album_info(RELEASE) is None


def test_a_response_without_an_album_object_is_unavailable() -> None:
    client, _, _ = make_client(inline({"something": "else"}))

    with pytest.raises(SourceUnavailable):
        client.album_info(RELEASE)


def test_rate_limiting_is_unavailable_whether_it_arrives_as_200_or_429() -> None:
    for status in (200, 429):
        client, _, _ = make_client(
            fixture("error_rate_limit", status), retry=RetryPolicy(max_retries=0)
        )

        with pytest.raises(SourceUnavailable, match="rate limiting"):
            client.album_info(RELEASE)


def test_a_bad_api_key_is_a_request_error_that_does_not_leak_the_key() -> None:
    client, _, _ = make_client(fixture("error_invalid_key", 403))

    with pytest.raises(SourceRequestError) as excinfo:
        client.top_albums("rock", 1)

    assert "LASTFM_API_KEY" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_other_lastfm_errors_are_request_errors_with_their_short_message() -> None:
    client, _, _ = make_client(inline({"error": 3, "message": "Invalid Method"}))

    with pytest.raises(SourceRequestError, match="error 3: Invalid Method"):
        client.top_albums("rock", 1)


@pytest.mark.parametrize("code", [8, 11, 16])
def test_temporary_lastfm_errors_are_unavailable(code: int) -> None:
    client, _, _ = make_client(inline({"error": code, "message": "try later"}))

    with pytest.raises(SourceUnavailable):
        client.top_albums("rock", 1)


def test_server_errors_are_retried_then_unavailable() -> None:
    client, transport, _ = make_client(
        HttpResponse(503, {}, b"<html>down</html>"), retry=RetryPolicy(max_retries=2)
    )

    with pytest.raises(SourceUnavailable):
        client.top_albums("rock", 1)

    assert len(transport.calls) == 3


@pytest.mark.parametrize(
    "outcome",
    [NetworkError("URLError"), HttpResponse(200, {}, b"<html>oops</html>"), inline([1])],
)
def test_network_failures_and_unusable_bodies_are_unavailable(
    outcome: HttpResponse | Exception,
) -> None:
    client, _, _ = make_client(outcome, retry=RetryPolicy(max_retries=0))

    with pytest.raises(SourceUnavailable):
        client.top_albums("rock", 1)


def test_the_key_is_not_in_the_repr() -> None:
    client, _, _ = make_client(fixture("top_albums_page1"))

    assert API_KEY not in repr(client)
