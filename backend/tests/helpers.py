import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from catalog.http import HttpResponse

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_bytes(relative_path: str) -> bytes:
    return (FIXTURES / relative_path).read_bytes()


def json_response(
    status: int, relative_path: str, headers: Mapping[str, str] | None = None
) -> HttpResponse:
    return HttpResponse(status, headers or {}, fixture_bytes(relative_path))


class FakeTransport:
    """Replays queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, *outcomes: HttpResponse | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json.loads(body) if body else None,
                "timeout": timeout,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    """A controllable clock whose sleep advances time, for throttle and retry tests."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
