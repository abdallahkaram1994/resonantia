import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer") from None
    if value < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ImproperlyConfigured(f"{name} must be at most {maximum}")
    return value


SECRET_KEY = require_env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()
]

INSTALLED_APPS = [
    "rest_framework",
    "core",
    "catalog",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": require_env("POSTGRES_DB"),
        "USER": require_env("POSTGRES_USER"),
        "PASSWORD": require_env("POSTGRES_PASSWORD"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "OPTIONS": {"connect_timeout": int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "5"))},
    }
}

# Anonymous v1: no accounts, so no auth apps and no default authentication or permissions.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

# Embeddings. Vectors from different models are never compared, so changing the model or the
# dimension means re-embedding the catalog. Set the rate to your Gemini quota, minus headroom.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "").strip() or "gemini-embedding-2"
EMBEDDING_DIM = env_int("EMBEDDING_DIM", 768)
EMBEDDING_REQUESTS_PER_MINUTE = env_int("EMBEDDING_REQUESTS_PER_MINUTE", 60)

# Film catalog (TMDB). Non-commercial use only; TMDB data must be refreshed within 6 months.
TMDB_READ_ACCESS_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN", "").strip()
TMDB_REQUESTS_PER_SECOND = env_int("TMDB_REQUESTS_PER_SECOND", 20)
TMDB_IMAGE_BASE_URL = (
    os.environ.get("TMDB_IMAGE_BASE_URL", "").strip() or "https://image.tmdb.org/t/p/w342"
)
TMDB_MAX_CACHE_DAYS = env_int("TMDB_MAX_CACHE_DAYS", 150)
# Films need at least this many TMDB votes to count as popular; a band just below it feeds the
# mid-tail slice so results can surprise. Vote counts pick films; they never affect ranking.
FILM_MIN_VOTE_COUNT = env_int("FILM_MIN_VOTE_COUNT", 1000)
FILM_MID_TAIL_MIN_VOTE_COUNT = env_int("FILM_MID_TAIL_MIN_VOTE_COUNT", 200)
FILM_MID_TAIL_PERCENT = env_int("FILM_MID_TAIL_PERCENT", 10, minimum=0, maximum=100)
CATALOG_TARGET_PER_TYPE = env_int("CATALOG_TARGET_PER_TYPE", 2000)
# Cap for sample runs (for example 50). 0 means use CATALOG_TARGET_PER_TYPE.
INGEST_LIMIT = env_int("INGEST_LIMIT", 0, minimum=0)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
