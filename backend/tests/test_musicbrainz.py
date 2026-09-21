"""MusicBrainz client tests, using invented records in the verified response shape (see
tests/fixtures/musicbrainz/README.md)."""

import json
from urllib.parse import urlsplit

import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceRequestError, SourceUnavailable
from catalog.sources.musicbrainz import (
    MusicBrainzClient,
    normalize_mbid,
    parse_release_year,
)
from tests.helpers import CountingThrottle, FakeClock, ScriptedTransport, fixture_bytes

AGENT = "Resonantia/0.1 (test@example.com)"
RELEASE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
GROUP = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def fixture(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, fixture_bytes(f"musicbrainz/{name}.json"))


def inline(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload).encode())


def make_client(handler, **overrides: object):
    transport = ScriptedTransport(handler)
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "user_agent": AGENT,
        "throttle": throttle,
        "transport": transport,
        "sleep": clock.sleep,
    }
    kwargs.update(overrides)
    return MusicBrainzClient(**kwargs), transport, throttle  # type: ignore[arg-type]


def always(response: HttpResponse | Exception):
    return lambda method, url, headers, body: response


def test_a_release_resolves_to_its_release_group() -> None:
    client, transport, _ = make_client(always(fixture("release")))

    assert client.release_group_id(RELEASE.upper()) == GROUP

    call = transport.calls[0]
    parts = urlsplit(call["url"])
    assert call["method"] == "GET"
    assert parts.netloc == "musicbrainz.org"
    assert parts.path == f"/ws/2/release/{RELEASE}"
    assert parts.query == "inc=release-groups&fmt=json"
    assert call["headers"]["User-Agent"] == AGENT


def test_release_group_details_are_parsed() -> None:
    client, transport, _ = make_client(always(fixture("release_group")))

    group = client.release_group(GROUP)

    assert group is not None
    assert group.mbid == GROUP
    assert group.title == "The Rainy Hour"
    assert group.artist == "Fixture Band"
    assert (group.primary_type, group.secondary_types) == ("Album", ())
    assert group.release_year == 1997
    assert group.wikidata_id == "Q900001"
    assert group.is_studio_album is True
    # The "+" between inc values must reach MusicBrainz literally, not as %2B.
    assert "inc=artist-credits+url-rels" in transport.calls[0]["url"]


def test_credited_artists_are_joined_with_their_join_phrases() -> None:
    client, _, _ = make_client(always(fixture("release_group_duo")))

    group = client.release_group("eeeeeeee-5555-4555-8555-eeeeeeeeeeee")

    assert group is not None
    assert group.artist == "Simon Example & Garfield Sample"
    assert group.release_year == 1969
    assert group.wikidata_id is None  # no relations at all


def test_a_live_album_is_not_a_studio_album() -> None:
    client, _, _ = make_client(always(fixture("release_group_live")))

    group = client.release_group("dddddddd-4444-4444-8444-dddddddddddd")

    assert group is not None
    assert group.secondary_types == ("Live",)
    assert group.release_year == 2001
    assert group.is_studio_album is False


@pytest.mark.parametrize(
    ("primary", "secondary", "expected"),
    [
        ("Album", [], True),
        ("Album", ["Compilation"], False),
        ("Album", ["Soundtrack", "Live"], False),
        ("EP", [], False),
        ("Single", [], False),
        ("", [], False),
    ],
)
def test_only_a_primary_album_with_no_secondary_type_counts(
    primary: str, secondary: list[str], expected: bool
) -> None:
    body = json.loads(fixture_bytes("musicbrainz/release_group.json"))
    body["primary-type"], body["secondary-types"] = primary, secondary
    client, _, _ = make_client(always(inline(body)))

    assert client.release_group(GROUP).is_studio_album is expected  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("value", "year"),
    [
        ("1997-05-21", 1997),
        ("1997-05", 1997),
        ("1997", 1997),
        ("", None),
        ("  ", None),
        ("97", None),
        ("1997-13-45x", None),
        ("0001-01-01", None),
        ("9999", None),
        (1997, None),
        (None, None),
    ],
)
def test_partial_and_missing_release_dates(value: object, year: int | None) -> None:
    assert parse_release_year(value) == year


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (GROUP, GROUP),
        (f"  {GROUP.upper()} ", GROUP),
        ("", None),
        ("not-an-id", None),
        ("../../etc/passwd", None),
        (f"{GROUP}/extra", None),
        (f"{GROUP}?x=1", None),
        (None, None),
        (123, None),
    ],
)
def test_ids_are_checked_before_they_reach_a_url(value: object, expected: str | None) -> None:
    assert normalize_mbid(value) == expected


@pytest.mark.parametrize("bad", ["", "nope", "../x", f"{GROUP}/../{GROUP}"])
def test_a_malformed_id_is_never_sent_to_musicbrainz(bad: str) -> None:
    client, transport, _ = make_client(always(fixture("release")))

    assert client.release_group_id(bad) is None
    assert client.release_group(bad) is None
    assert transport.calls == []


def test_an_unknown_id_is_none_not_an_error() -> None:
    client, _, _ = make_client(always(inline({"error": "Not Found"}, 404)))

    assert client.release_group_id(RELEASE) is None
    assert client.release_group(GROUP) is None


def test_a_release_without_a_release_group_is_none() -> None:
    client, _, _ = make_client(always(inline({"id": RELEASE, "title": "x"})))

    assert client.release_group_id(RELEASE) is None


@pytest.mark.parametrize(
    "relations",
    [
        None,
        "wikidata",
        [None, 3, {"type": "wikidata"}, {"type": "wikidata", "url": "x"}],
        [{"type": "wikidata", "url": {"resource": "https://evil.example/wiki/Q1"}}],
        [{"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q0"}}],
        [{"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Qabc"}}],
        [{"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q1/../x"}}],
        [{"type": "wikidata", "url": {"resource": 7}}],
    ],
)
def test_only_a_real_wikidata_link_gives_a_wikidata_id(relations: object) -> None:
    body = json.loads(fixture_bytes("musicbrainz/release_group.json"))
    body["relations"] = relations
    client, _, _ = make_client(always(inline(body)))

    assert client.release_group(GROUP).wikidata_id is None  # type: ignore[union-attr]


def test_hostile_field_values_are_neutralised() -> None:
    body = {
        "title": "T" * 2000,
        "primary-type": ["Album"],
        "secondary-types": "Live",
        "first-release-date": ["1997"],
        "artist-credit": "Radiohead",
    }
    client, _, _ = make_client(always(inline(body)))

    group = client.release_group(GROUP)

    assert group is not None
    assert len(group.title) == 500
    assert (group.primary_type, group.secondary_types) == ("", ())
    assert group.release_year is None
    assert group.artist == ""
    assert group.is_studio_album is False


def test_a_release_group_without_a_title_is_dropped() -> None:
    client, _, _ = make_client(always(inline({"title": "   ", "primary-type": "Album"})))

    assert client.release_group(GROUP) is None


def test_every_request_is_throttled_and_identifies_us() -> None:
    client, transport, throttle = make_client(always(fixture("release_group")))

    client.release_group(GROUP)
    client.release_group(GROUP)

    assert throttle.waits == 2
    assert all(c["headers"]["User-Agent"] == AGENT for c in transport.calls)


def test_rate_limiting_that_never_clears_is_unavailable() -> None:
    client, transport, _ = make_client(
        always(HttpResponse(503, {}, b"{}")), retry=RetryPolicy(max_retries=2)
    )

    with pytest.raises(SourceUnavailable):
        client.release_group(GROUP)

    assert len(transport.calls) == 3


def test_a_rejected_request_is_a_request_error() -> None:
    client, _, _ = make_client(always(inline({"error": "bad"}, 400)))

    with pytest.raises(SourceRequestError, match="HTTP 400"):
        client.release_group(GROUP)


@pytest.mark.parametrize(
    "outcome",
    [NetworkError("URLError"), HttpResponse(200, {}, b"<html>oops</html>"), inline([1, 2])],
)
def test_network_failures_and_unusable_bodies_are_unavailable(
    outcome: HttpResponse | Exception,
) -> None:
    client, _, _ = make_client(always(outcome), retry=RetryPolicy(max_retries=0))

    with pytest.raises(SourceUnavailable):
        client.release_group(GROUP)
