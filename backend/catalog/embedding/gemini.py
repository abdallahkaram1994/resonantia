import json
import math
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from catalog.embedding.base import (
    EmbeddingError,
    EmbeddingRateLimited,
    EmbeddingRequestError,
    EmbeddingUnavailable,
    EmbedKind,
)
from catalog.http import (
    HttpError,
    HttpResponse,
    NetworkError,
    RetryPolicy,
    Transport,
    request_json,
    urllib_transport,
)
from catalog.ratelimit import Throttle

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
_SERVER_ERRORS = frozenset({500, 502, 503, 504})


def _error_code(response: HttpResponse) -> str | None:
    try:
        error = json.loads(response.body).get("error")
        code = error.get("code") if isinstance(error, dict) else None
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, str) else None


def _error_message(response: HttpResponse) -> str:
    try:
        message = json.loads(response.body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP {response.status}"
    return f"HTTP {response.status}: {str(message)[:200]}"


def _is_retryable(response: HttpResponse) -> bool:
    if response.status == 429:
        return _error_code(response) != "quota_exceeded"
    return response.status in _SERVER_ERRORS


def format_text(text: str, kind: EmbedKind) -> str:
    """gemini-embedding-2 takes retrieval instructions inside the text, not a task_type field.

    Our combined text already starts with the title, so documents use Google's "no title" form.
    """
    if kind == "query":
        return f"task: search result | query: {text}"
    if kind == "document":
        return f"title: none | text: {text}"
    raise ValueError(f"Unknown embed kind: {kind!r}")


class GeminiEmbedder:
    """Embeds one text per request. A list of texts in one call would return a single aggregated
    vector on gemini-embedding-2, so texts are never combined."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        throttle: Throttle,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        if not _MODEL_NAME.match(model):
            raise ValueError(f"Invalid embedding model name: {model!r}")
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._throttle = throttle
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._base_url = base_url

    def __repr__(self) -> str:
        return f"GeminiEmbedder(model={self.model!r}, dimensions={self.dimensions})"

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> list[list[float]]:
        return [self._embed_one(text, kind) for text in texts]

    def _embed_one(self, text: str, kind: EmbedKind) -> list[float]:
        self._throttle.wait()
        body = {
            "content": {"parts": [{"text": format_text(text, kind)}]},
            "outputDimensionality": self.dimensions,
        }
        url = f"{self._base_url}/models/{self.model}:embedContent"
        try:
            data = request_json(
                self._transport,
                "POST",
                url,
                headers={"x-goog-api-key": self._api_key},
                json_body=body,
                timeout=self._timeout,
                retry=self._retry,
                is_retryable=_is_retryable,
                sleep=self._sleep,
            )
        except HttpError as error:
            raise self._map_http_error(error) from error
        except NetworkError as error:
            raise EmbeddingUnavailable("Could not reach the Gemini API") from error
        except ValueError as error:
            raise EmbeddingUnavailable("Gemini returned a response that is not JSON") from error
        return self._parse(data)

    @staticmethod
    def _map_http_error(error: HttpError) -> EmbeddingError:
        response = error.response
        message = _error_message(response)
        if response.status == 429:
            return EmbeddingRateLimited(
                message,
                retry_after=error.retry_after,
                quota_exhausted=_error_code(response) == "quota_exceeded",
            )
        if response.status in _SERVER_ERRORS:
            return EmbeddingUnavailable(message)
        return EmbeddingRequestError(message)

    def _parse(self, data: Any) -> list[float]:
        try:
            values = data["embedding"]["values"]
        except (KeyError, TypeError) as error:
            raise EmbeddingUnavailable("Gemini response has no embedding values") from error
        if not isinstance(values, list) or not all(
            isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
            for v in values
        ):
            raise EmbeddingUnavailable("Gemini embedding contains non-numeric values")
        if len(values) != self.dimensions:
            raise EmbeddingRequestError(
                f"Expected {self.dimensions} dimensions from {self.model}, got {len(values)}"
            )
        return [float(v) for v in values]
