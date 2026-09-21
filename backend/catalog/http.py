import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class NetworkError(Exception):
    """The request never produced an HTTP response (DNS, connection, timeout)."""


class HttpError(Exception):
    """A non-success HTTP response. Never carries request headers, so secrets stay out of logs."""

    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.status = response.status
        super().__init__(f"HTTP {response.status}")

    @property
    def retry_after(self) -> float | None:
        return parse_retry_after(self.response.headers)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None  # report the 3xx as it is instead of following it


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _send(
    open_url: Callable[..., Any],
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with open_url(request, timeout=timeout) as response:
            return HttpResponse(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as error:
        return HttpResponse(error.code, dict(error.headers), error.read())
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise NetworkError(type(error).__name__) from error


def urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    return _send(urllib.request.urlopen, method, url, headers, body, timeout)


def urllib_transport_no_redirect(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    """Like urllib_transport, but a 3xx answer is returned as it is, not followed."""
    return _send(_NO_REDIRECT_OPENER.open, method, url, headers, body, timeout)


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                seconds = float(value)
            except ValueError:
                return None  # an HTTP-date form is not worth supporting here
            return seconds if seconds >= 0 else None
    return None


def request_json(
    transport: Transport,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: Any = None,
    data: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    is_retryable: Callable[[HttpResponse], bool] | None = None,
    retry_after_of: Callable[[HttpResponse], float | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Send a JSON request, retrying transient failures, and return the parsed JSON body.

    Retries 429 and 5xx (and network errors) with exponential backoff. A server-provided delay
    (the Retry-After header, or whatever `retry_after_of` extracts, such as a delay in the body)
    longer than `retry.max_delay` is not waited out: the error is raised at once so the caller can
    stop (for example, a daily quota) instead of blocking. A 2xx body that is not valid JSON raises
    ValueError. `data` sends a raw body (for example a form or a plain-text query) instead of JSON.
    """
    retry = retry or RetryPolicy()
    if json_body is not None and data is not None:
        raise ValueError("Pass either json_body or data, not both")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    if data is not None:
        request_headers["Content-Type"] = content_type

    def retryable(response: HttpResponse) -> bool:
        if is_retryable is not None:
            return is_retryable(response)
        return response.status in RETRYABLE_STATUSES

    for attempt in range(retry.max_retries + 1):
        last_attempt = attempt == retry.max_retries
        try:
            response = transport(method, url, request_headers, data, timeout)
        except NetworkError:
            if last_attempt:
                raise
            sleep(min(retry.base_delay * 2**attempt, retry.max_delay))
            continue

        if 200 <= response.status < 300:
            return json.loads(response.body)

        error = HttpError(response)
        if last_attempt or not retryable(response):
            raise error
        wait = retry_after_of(response) if retry_after_of else error.retry_after
        if wait is not None and wait > retry.max_delay:
            raise error
        sleep(wait if wait is not None else min(retry.base_delay * 2**attempt, retry.max_delay))

    raise AssertionError("unreachable")  # pragma: no cover
