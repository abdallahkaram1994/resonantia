import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from catalog.llm.factory import get_llm
from catalog.llm.gemini import GeminiLLM
from tests.helpers import load_settings_value


def test_llm_needs_an_api_key() -> None:
    with override_settings(GEMINI_API_KEY=""), pytest.raises(ImproperlyConfigured):
        get_llm()


def test_llm_is_built_from_settings() -> None:
    with override_settings(
        GEMINI_API_KEY="k",
        GEMINI_LLM_MODEL="gemini-3.5-flash-lite",
        LLM_REQUESTS_PER_MINUTE=15,
    ):
        llm = get_llm()

    assert isinstance(llm, GeminiLLM)
    assert llm.model == "gemini-3.5-flash-lite"


def test_settings_defaults_when_nothing_is_set() -> None:
    result = load_settings_value("GEMINI_LLM_MODEL", {})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gemini-3.5-flash-lite"


def test_the_default_request_rate() -> None:
    result = load_settings_value("LLM_REQUESTS_PER_MINUTE", {})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10"


@pytest.mark.parametrize("bad", ["0", "-3", "many", "1.5"])
def test_settings_reject_a_bad_request_rate(bad: str) -> None:
    result = load_settings_value("LLM_REQUESTS_PER_MINUTE", {"LLM_REQUESTS_PER_MINUTE": bad})

    assert result.returncode != 0
    assert "LLM_REQUESTS_PER_MINUTE" in result.stderr
