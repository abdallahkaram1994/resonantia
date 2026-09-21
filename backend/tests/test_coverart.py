import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceUnavailable
from catalog.sources.coverart import CoverArtArchive
from tests.helpers import CountingThrottle, FakeClock, ScriptedTransport

AGENT = "Resonantia/0.1 (test@example.com)"
GROUP = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
URL_500 = f"https://coverartarchive.org/release-group/{GROUP}/front-500"


def make_archive(outcome: HttpResponse | Exception, **overrides: object):
    transport = ScriptedTransport(lambda method, url, headers, body: outcome)
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "user_agent": AGENT,
        "throttle": throttle,
        "transport": transport,
        "sleep": clock.sleep,
    }
    kwargs.update(overrides)
    return CoverArtArchive(**kwargs), transport, throttle  # type: ignore[arg-type]


@pytest.mark.parametrize("status", [307, 302, 301, 303, 308])
def test_a_redirect_means_a_front_cover_exists(status: int) -> None:
    archive, transport, _ = make_archive(
        HttpResponse(status, {"Location": "https://archive.org/download/x.jpg"}, b"")
    )

    assert archive.front_cover_url(GROUP) == URL_500

    call = transport.calls[0]
    assert call["method"] == "HEAD"
    assert call["url"] == URL_500
    assert call["headers"]["User-Agent"] == AGENT


def test_the_stored_url_is_the_stable_one_by_id_not_the_redirect_target() -> None:
    archive, _, _ = make_archive(
        HttpResponse(307, {"Location": "https://archive.org/download/mbid-x/mbid-x-1_thumb"}, b"")
    )

    url = archive.front_cover_url(GROUP.upper())

    assert url == URL_500
    assert "download" not in url and not url.startswith("https://archive.org")


def test_no_front_cover_is_none_not_an_error() -> None:
    archive, _, _ = make_archive(HttpResponse(404, {}, b""))

    assert archive.front_cover_url(GROUP) is None


def test_a_plain_success_without_a_body_also_counts() -> None:
    archive, _, _ = make_archive(HttpResponse(200, {}, b""))

    assert archive.front_cover_url(GROUP) == URL_500


@pytest.mark.parametrize("size", [250, 500, 1200])
def test_the_cover_size_is_part_of_the_url(size: int) -> None:
    archive, _, _ = make_archive(HttpResponse(307, {}, b""), size=size)

    assert archive.front_cover_url(GROUP).endswith(f"/front-{size}")  # type: ignore[union-attr]


@pytest.mark.parametrize("size", [0, 100, 501, -1])
def test_an_unsupported_cover_size_is_rejected(size: int) -> None:
    with pytest.raises(ValueError):
        make_archive(HttpResponse(307, {}, b""), size=size)


@pytest.mark.parametrize("bad", ["", "nope", "../x", f"{GROUP}/../{GROUP}"])
def test_a_malformed_id_is_never_sent(bad: str) -> None:
    archive, transport, _ = make_archive(HttpResponse(307, {}, b""))

    assert archive.front_cover_url(bad) is None
    assert transport.calls == []


def test_every_check_is_throttled() -> None:
    archive, _, throttle = make_archive(HttpResponse(404, {}, b""))

    archive.front_cover_url(GROUP)
    archive.front_cover_url(GROUP)

    assert throttle.waits == 2


def test_not_knowing_is_never_reported_as_no_cover() -> None:
    """An outage must stop the run so the album is retried, not stored without a cover for good."""
    archive, transport, _ = make_archive(
        HttpResponse(503, {}, b""), retry=RetryPolicy(max_retries=2)
    )

    with pytest.raises(SourceUnavailable):
        archive.front_cover_url(GROUP)

    assert len(transport.calls) == 3


@pytest.mark.parametrize("status", [400, 403, 500])
def test_unexpected_statuses_are_unavailable(status: int) -> None:
    archive, _, _ = make_archive(HttpResponse(status, {}, b""), retry=RetryPolicy(max_retries=0))

    with pytest.raises(SourceUnavailable):
        archive.front_cover_url(GROUP)


def test_a_network_failure_is_unavailable() -> None:
    archive, _, _ = make_archive(NetworkError("URLError"), retry=RetryPolicy(max_retries=0))

    with pytest.raises(SourceUnavailable):
        archive.front_cover_url(GROUP)


def test_the_default_transport_does_not_follow_redirects() -> None:
    """Following the 307 would fetch the whole image from archive.org for every album checked."""
    from catalog.http import urllib_transport_no_redirect

    archive = CoverArtArchive(user_agent=AGENT, throttle=CountingThrottle())

    assert archive._transport is urllib_transport_no_redirect
