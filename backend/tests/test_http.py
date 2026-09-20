import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from catalog.http import (
    HttpError,
    HttpResponse,
    NetworkError,
    RetryPolicy,
    parse_retry_after,
    request_json,
    urllib_transport,
)
from tests.helpers import FakeClock, FakeTransport

URL = "https://example.test/api"


def ok(payload: object = None) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps(payload or {"ok": True}).encode())


def status(code: int, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(code, headers or {}, b'{"error": "nope"}')


def call(transport: FakeTransport, clock: FakeClock, **kwargs: object) -> object:
    return request_json(transport, "POST", URL, sleep=clock.sleep, **kwargs)


def test_success_returns_parsed_json_and_sends_a_json_body_and_headers() -> None:
    transport = FakeTransport(ok({"a": 1}))

    result = request_json(
        transport, "POST", URL, headers={"X-Test": "1"}, json_body={"q": "café"}, timeout=7
    )

    assert result == {"a": 1}
    sent = transport.calls[0]
    assert sent["method"] == "POST"
    assert sent["json"] == {"q": "café"}
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["headers"]["X-Test"] == "1"
    assert sent["timeout"] == 7


def test_transient_errors_are_retried_with_exponential_backoff() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(503), status(500), ok())

    assert call(transport, clock) == {"ok": True}

    assert len(transport.calls) == 3
    assert clock.sleeps == [1.0, 2.0]


def test_backoff_is_capped_by_max_delay() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(503), status(503), status(503), ok())

    call(transport, clock, retry=RetryPolicy(max_retries=3, base_delay=10, max_delay=15))

    assert clock.sleeps == [10, 15, 15]


def test_retry_after_is_honored_when_short_enough() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(429, {"Retry-After": "7"}), ok())

    call(transport, clock)

    assert clock.sleeps == [7.0]


def test_retry_after_longer_than_max_delay_fails_fast_without_sleeping() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(429, {"Retry-After": "3600"}), ok())

    with pytest.raises(HttpError) as excinfo:
        call(transport, clock)

    assert excinfo.value.status == 429
    assert excinfo.value.retry_after == 3600
    assert clock.sleeps == []
    assert len(transport.calls) == 1


def test_client_errors_are_not_retried() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(400), ok())

    with pytest.raises(HttpError) as excinfo:
        call(transport, clock)

    assert excinfo.value.status == 400
    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_gives_up_after_max_retries() -> None:
    clock = FakeClock()
    transport = FakeTransport(*[status(503)] * 4, ok())

    with pytest.raises(HttpError):
        call(transport, clock, retry=RetryPolicy(max_retries=3))

    assert len(transport.calls) == 4


def test_custom_retry_rule_can_veto_a_retry() -> None:
    clock = FakeClock()
    transport = FakeTransport(status(429), ok())

    with pytest.raises(HttpError):
        call(transport, clock, is_retryable=lambda response: False)

    assert len(transport.calls) == 1


def test_network_errors_are_retried_then_raised() -> None:
    clock = FakeClock()
    transport = FakeTransport(NetworkError("URLError"), ok())
    assert call(transport, clock) == {"ok": True}

    transport = FakeTransport(*[NetworkError("URLError")] * 4)
    with pytest.raises(NetworkError):
        call(transport, clock, retry=RetryPolicy(max_retries=3))
    assert len(transport.calls) == 4


def test_a_success_response_that_is_not_json_raises_value_error() -> None:
    transport = FakeTransport(HttpResponse(200, {}, b"<html>oops</html>"))

    with pytest.raises(ValueError):
        request_json(transport, "GET", URL)


def test_http_error_never_exposes_request_headers() -> None:
    transport = FakeTransport(status(403))

    with pytest.raises(HttpError) as excinfo:
        request_json(transport, "GET", URL, headers={"x-goog-api-key": "super-secret-key"})

    assert "super-secret-key" not in str(excinfo.value)
    assert "super-secret-key" not in repr(excinfo.value)


def test_parse_retry_after() -> None:
    assert parse_retry_after({"Retry-After": "12"}) == 12.0
    assert parse_retry_after({"retry-after": "1.5"}) == 1.5
    assert parse_retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None
    assert parse_retry_after({"Retry-After": "-5"}) is None
    assert parse_retry_after({}) is None


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        received = json.loads(self.rfile.read(length))
        if self.path == "/limited":
            payload, code, extra = {"error": "slow down"}, 429, {"Retry-After": "9"}
        else:
            payload, code, extra = {"echo": received, "auth": self.headers.get("X-Key")}, 200, {}
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_real_transport_round_trips_json_against_a_local_server(local_server: str) -> None:
    result = request_json(
        urllib_transport, "POST", local_server + "/ok", headers={"X-Key": "k"}, json_body={"n": 1}
    )

    assert result == {"echo": {"n": 1}, "auth": "k"}


def test_real_transport_returns_error_statuses_instead_of_raising(local_server: str) -> None:
    response = urllib_transport("POST", local_server + "/limited", {}, b"{}", 5.0)

    assert response.status == 429
    assert parse_retry_after(response.headers) == 9


def test_real_transport_turns_connection_failures_into_network_error() -> None:
    with pytest.raises(NetworkError):
        urllib_transport("GET", "http://127.0.0.1:1/", {}, None, 2.0)
