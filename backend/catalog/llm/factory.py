from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from catalog.llm.base import LLM
from catalog.llm.gemini import GeminiLLM
from catalog.ratelimit import Throttle


def get_llm() -> LLM:
    if not settings.GEMINI_API_KEY:
        raise ImproperlyConfigured("GEMINI_API_KEY is not set")
    return GeminiLLM(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_LLM_MODEL,
        throttle=Throttle(60.0 / settings.LLM_REQUESTS_PER_MINUTE),
    )
