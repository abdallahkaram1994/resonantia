from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from catalog.embedding.base import Embedder
from catalog.embedding.gemini import GeminiEmbedder
from catalog.ratelimit import Throttle


def get_embedder() -> Embedder:
    if not settings.GEMINI_API_KEY:
        raise ImproperlyConfigured("GEMINI_API_KEY is not set")
    return GeminiEmbedder(
        api_key=settings.GEMINI_API_KEY,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIM,
        throttle=Throttle(60.0 / settings.EMBEDDING_REQUESTS_PER_MINUTE),
    )
