import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from catalog.http import HttpResponse
from catalog.ratelimit import Throttle

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_ENV = {
    "DJANGO_SECRET_KEY": "test-secret",
    "POSTGRES_DB": "db",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "password",
}


def load_settings_value(name: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Print one setting from a fresh interpreter whose environment is exactly BASE_ENV + extras."""
    env = {"PATH": os.environ["PATH"], "DJANGO_SETTINGS_MODULE": "config.settings"}
    env.update(BASE_ENV)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", f"from django.conf import settings; print(settings.{name})"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


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


class RoutingTransport:
    """Answers each request by calling `handler(path, query)`; records every call."""

    def __init__(self, handler: Callable[[str, dict[str, str]], HttpResponse | Exception]) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        parsed = urlsplit(url)
        query = {name: values[0] for name, values in parse_qs(parsed.query).items()}
        self.calls.append(
            {
                "method": method,
                "url": url,
                "path": parsed.path,
                "query": query,
                "headers": dict(headers),
            }
        )
        outcome = self._handler(parsed.path, query)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class CountingThrottle(Throttle):
    """A throttle that never sleeps and only counts how often it was asked to wait."""

    def __init__(self) -> None:
        super().__init__(0)
        self.waits = 0

    def wait(self) -> None:
        self.waits += 1


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
