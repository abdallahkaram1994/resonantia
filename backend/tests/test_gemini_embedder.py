"""Gemini adapter tests. Fixtures under tests/fixtures/gemini follow Google's API reference
(embedContent response, `{"error": {"code", "message"}}` bodies); replace them with recordings
from the live API when a key is available."""

import json

import pytest

from catalog.embedding.base import (
    EmbeddingRateLimited,
    EmbeddingRequestError,
    EmbeddingUnavailable,
)
from catalog.embedding.gemini import GeminiEmbedder, format_text
from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.ratelimit import Throttle
from tests.helpers import FakeClock, FakeTransport, fixture_bytes, json_response

API_KEY = "test-key-not-real"
DIMS = 4


class CountingThrottle(Throttle):
    def __init__(self) -> None:
        super().__init__(0)
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


def make_embedder(*outcomes: HttpResponse | Exception, **overrides: object):
    transport = FakeTransport(*outcomes)
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "api_key": API_KEY,
        "model": "gemini-embedding-2",
        "dimensions": DIMS,
        "throttle": CountingThrottle(),
        "transport": transport,
        "sleep": clock.sleep,
    }
    kwargs.update(overrides)
    return GeminiEmbedder(**kwargs), transport, clock  # type: ignore[arg-type]


def ok() -> HttpResponse:
    return json_response(200, "gemini/embed_ok.json")


def test_request_shape_for_a_query() -> None:
    embedder, transport, _ = make_embedder(ok())

    embedder.embed(["a rainy night drive"], "query")

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
    )
    assert call["headers"]["x-goog-api-key"] == API_KEY
    assert API_KEY not in call["url"]
    assert call["json"] == {
        "content": {"parts": [{"text": "task: search result | query: a rainy night drive"}]},
        "outputDimensionality": DIMS,
    }


def test_documents_use_the_no_title_prefix() -> None:
    embedder, transport, _ = make_embedder(ok())

    embedder.embed(["Heat\nGenres: Crime"], "document")

    text = transport.calls[0]["json"]["content"]["parts"][0]["text"]
    assert text == "title: none | text: Heat\nGenres: Crime"


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        format_text("x", "other")  # type: ignore[arg-type]


def test_each_text_is_its_own_request_so_vectors_are_never_aggregated() -> None:
    embedder, transport, _ = make_embedder(ok(), ok(), ok())

    vectors = embedder.embed(["one", "two", "three"], "document")

    assert len(vectors) == 3
    assert len(transport.calls) == 3
    for call, expected in zip(transport.calls, ["one", "two", "three"], strict=True):
        parts = call["json"]["content"]["parts"]
        assert len(parts) == 1
        assert parts[0]["text"].endswith(expected)


def test_vectors_are_returned_as_floats_in_order() -> None:
    first = HttpResponse(200, {}, json.dumps({"embedding": {"values": [1, 2, 3, 4]}}).encode())
    second = HttpResponse(200, {}, json.dumps({"embedding": {"values": [5, 6, 7, 8]}}).encode())
    embedder, _, _ = make_embedder(first, second)

    vectors = embedder.embed(["a", "b"], "document")

    assert vectors == [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]
    assert all(isinstance(v, float) for v in vectors[0])


def test_no_texts_makes_no_requests() -> None:
    embedder, transport, _ = make_embedder()

    assert embedder.embed([], "document") == []
    assert transport.calls == []


def test_throttle_is_applied_once_per_text() -> None:
    throttle = CountingThrottle()
    embedder, _, _ = make_embedder(ok(), ok(), throttle=throttle)

    embedder.embed(["a", "b"], "document")

    assert throttle.waits == 2


def test_wrong_dimension_is_a_request_error() -> None:
    embedder, _, _ = make_embedder(ok(), dimensions=8)

    with pytest.raises(EmbeddingRequestError, match="Expected 8 dimensions"):
        embedder.embed(["a"], "document")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"embedding": {}},
        {"embedding": {"values": "nope"}},
        {"embedding": {"values": [0.1, "x", 0.3, 0.4]}},
        {"embedding": {"values": [0.1, True, 0.3, 0.4]}},
        {"embedding": {"values": [0.1, None, 0.3, 0.4]}},
        [],
    ],
)
def test_malformed_success_bodies_are_unavailable(payload: object) -> None:
    embedder, _, _ = make_embedder(HttpResponse(200, {}, json.dumps(payload).encode()))

    with pytest.raises(EmbeddingUnavailable):
        embedder.embed(["a"], "document")


def test_non_finite_numbers_are_unavailable() -> None:
    body = b'{"embedding": {"values": [0.1, NaN, 0.3, 0.4]}}'
    embedder, _, _ = make_embedder(HttpResponse(200, {}, body))

    with pytest.raises(EmbeddingUnavailable):
        embedder.embed(["a"], "document")


def test_a_non_json_success_body_is_unavailable() -> None:
    embedder, _, _ = make_embedder(HttpResponse(200, {}, b"<html>gateway</html>"))

    with pytest.raises(EmbeddingUnavailable):
        embedder.embed(["a"], "document")


def test_bad_key_is_a_request_error_and_never_retried_or_leaked() -> None:
    embedder, transport, clock = make_embedder(json_response(400, "gemini/error_invalid_key.json"))

    with pytest.raises(EmbeddingRequestError) as excinfo:
        embedder.embed(["a"], "document")

    assert "API key not valid" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)
    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_per_minute_rate_limit_is_retried_then_succeeds() -> None:
    embedder, transport, clock = make_embedder(
        json_response(429, "gemini/error_rate_limit.json", {"Retry-After": "3"}), ok()
    )

    assert embedder.embed(["a"], "document") == [[0.1, 0.2, 0.3, 0.4]]

    assert len(transport.calls) == 2
    assert clock.sleeps == [3.0]


def test_daily_quota_is_not_retried_and_says_so() -> None:
    embedder, transport, clock = make_embedder(
        json_response(429, "gemini/error_quota_exceeded.json"), ok()
    )

    with pytest.raises(EmbeddingRateLimited) as excinfo:
        embedder.embed(["a"], "document")

    assert excinfo.value.quota_exhausted is True
    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_rate_limit_that_never_clears_raises_rate_limited() -> None:
    limited = json_response(429, "gemini/error_rate_limit.json")
    embedder, transport, _ = make_embedder(*[limited] * 4, retry=RetryPolicy(max_retries=3))

    with pytest.raises(EmbeddingRateLimited) as excinfo:
        embedder.embed(["a"], "document")

    assert excinfo.value.quota_exhausted is False
    assert len(transport.calls) == 4


def test_long_retry_after_fails_fast_and_reports_it() -> None:
    embedder, transport, clock = make_embedder(
        json_response(429, "gemini/error_rate_limit.json", {"Retry-After": "7200"})
    )

    with pytest.raises(EmbeddingRateLimited) as excinfo:
        embedder.embed(["a"], "document")

    assert excinfo.value.retry_after == 7200
    assert len(transport.calls) == 1
    assert clock.sleeps == []


def test_server_errors_are_retried_then_unavailable() -> None:
    down = HttpResponse(503, {}, b'{"error": {"code": "service_unavailable", "message": "x"}}')
    embedder, transport, _ = make_embedder(*[down] * 4, retry=RetryPolicy(max_retries=3))

    with pytest.raises(EmbeddingUnavailable):
        embedder.embed(["a"], "document")

    assert len(transport.calls) == 4


def test_network_failure_is_unavailable() -> None:
    embedder, _, _ = make_embedder(*[NetworkError("URLError")] * 4, retry=RetryPolicy())

    with pytest.raises(EmbeddingUnavailable):
        embedder.embed(["a"], "document")


def test_api_key_is_not_in_the_repr() -> None:
    embedder, _, _ = make_embedder()

    assert API_KEY not in repr(embedder)


@pytest.mark.parametrize("model", ["", "../etc/passwd", "models/x", "a b", "x?y=1", "UPPER"])
def test_model_names_that_could_alter_the_url_are_rejected(model: str) -> None:
    with pytest.raises(ValueError):
        make_embedder(model=model)


def test_fixture_files_are_valid_json() -> None:
    for name in ["embed_ok", "error_quota_exceeded", "error_rate_limit", "error_invalid_key"]:
        json.loads(fixture_bytes(f"gemini/{name}.json"))
