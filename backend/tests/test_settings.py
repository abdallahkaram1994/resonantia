import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import load_settings_value

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


def test_the_job_queue_app_is_loaded_before_the_projects_own_apps() -> None:
    from django.conf import settings

    apps = settings.INSTALLED_APPS
    assert apps.index("procrastinate.contrib.django") < apps.index("catalog")


def test_logging_defaults_to_info_and_goes_to_the_console() -> None:
    result = load_settings_value("LOGGING['root']", {})

    assert result.returncode == 0, result.stderr
    assert "'level': 'INFO'" in result.stdout
    assert "'handlers': ['console']" in result.stdout


@pytest.mark.parametrize(("given", "level"), [("debug", "DEBUG"), (" Warning ", "WARNING")])
def test_log_level_ignores_case_and_spaces(given: str, level: str) -> None:
    result = load_settings_value("LOG_LEVEL", {"LOG_LEVEL": given})

    assert result.stdout.strip() == level


@pytest.mark.parametrize("bad", ["loud", "10", "NOTSET"])
def test_an_unknown_log_level_is_refused_at_start_up(bad: str) -> None:
    result = load_settings_value("LOG_LEVEL", {"LOG_LEVEL": bad})

    assert result.returncode != 0
    assert "LOG_LEVEL must be" in result.stderr
