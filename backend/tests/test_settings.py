import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

VALID_ENV = {
    "DJANGO_SECRET_KEY": "test-secret",
    "POSTGRES_DB": "db",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "password",
}


def load_settings(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # A subprocess with an explicit environment keeps this test independent of the test run's env.
    full_env = {"PATH": os.environ["PATH"], "DJANGO_SETTINGS_MODULE": "config.settings", **env}
    return subprocess.run(
        [sys.executable, "-c", "from django.conf import settings; settings.SECRET_KEY"],
        cwd=BACKEND_DIR,
        env=full_env,
        capture_output=True,
        text=True,
    )


def test_settings_load_with_required_env() -> None:
    result = load_settings(VALID_ENV)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing", sorted(VALID_ENV))
def test_settings_refuse_to_load_without_required_env(missing: str) -> None:
    env = {name: value for name, value in VALID_ENV.items() if name != missing}

    result = load_settings(env)

    assert result.returncode != 0
    assert missing in result.stderr
