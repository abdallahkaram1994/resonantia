import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from catalog.embedding.factory import get_embedder
from catalog.embedding.gemini import GeminiEmbedder

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_ENV = {
    "DJANGO_SECRET_KEY": "test-secret",
    "POSTGRES_DB": "db",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "password",
}


def load_settings_value(name: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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


def test_defaults_match_the_column_width_and_pass_system_checks() -> None:
    assert [e for e in run_checks() if e.id == "catalog.E001"] == []


def test_system_check_fails_when_dimension_differs_from_the_column() -> None:
    with override_settings(EMBEDDING_DIM=512):
        ids = [e.id for e in run_checks()]

    assert "catalog.E001" in ids


def test_embedder_needs_an_api_key() -> None:
    with override_settings(GEMINI_API_KEY=""), pytest.raises(ImproperlyConfigured):
        get_embedder()


def test_embedder_is_built_from_settings() -> None:
    with override_settings(
        GEMINI_API_KEY="k",
        EMBEDDING_MODEL="gemini-embedding-2",
        EMBEDDING_DIM=768,
        EMBEDDING_REQUESTS_PER_MINUTE=30,
    ):
        embedder = get_embedder()

    assert isinstance(embedder, GeminiEmbedder)
    assert embedder.model == "gemini-embedding-2"
    assert embedder.dimensions == 768


def test_settings_defaults_when_nothing_is_set() -> None:
    result = load_settings_value("EMBEDDING_MODEL", {})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gemini-embedding-2"


@pytest.mark.parametrize("bad", ["0", "-3", "many", "1.5"])
def test_settings_reject_a_bad_request_rate(bad: str) -> None:
    result = load_settings_value(
        "EMBEDDING_REQUESTS_PER_MINUTE", {"EMBEDDING_REQUESTS_PER_MINUTE": bad}
    )

    assert result.returncode != 0
    assert "EMBEDDING_REQUESTS_PER_MINUTE" in result.stderr
