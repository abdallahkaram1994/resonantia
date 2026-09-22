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


def env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be a number") from None
    if value < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}")
    return value


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
    # Procrastinate (the Postgres-backed task queue) must come before the apps that define tasks.
    "procrastinate.contrib.django",
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

# Game catalog (IGDB, through a Twitch app's client credentials). Free for non-commercial use.
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
IGDB_REQUESTS_PER_SECOND = env_int("IGDB_REQUESTS_PER_SECOND", 3)
IGDB_COVER_SIZE = os.environ.get("IGDB_COVER_SIZE", "").strip() or "t_cover_big"
# A game needs this many ratings to count as popular; a band below it feeds the mid-tail slice.
# Rating counts only select games. They never affect ranking.
GAME_MIN_RATING_COUNT = env_int("GAME_MIN_RATING_COUNT", 75)
GAME_MID_TAIL_MIN_RATING_COUNT = env_int("GAME_MID_TAIL_MIN_RATING_COUNT", 25)
# IGDB keywords are user tags and some games have hundreds, so only this many go into the text.
GAME_MAX_KEYWORDS = env_int("GAME_MAX_KEYWORDS", 10, minimum=0)

# Album catalog: Last.fm finds popular albums and their tags, MusicBrainz identifies them, the
# Cover Art Archive supplies covers and Wikipedia the summaries. Non-commercial use only.
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "").strip()
LASTFM_REQUESTS_PER_SECOND = env_int("LASTFM_REQUESTS_PER_SECOND", 2)
# Listener counts pick albums. They never affect ranking.
ALBUM_MIN_LISTENERS = env_int("ALBUM_MIN_LISTENERS", 50000)
ALBUM_MID_TAIL_MIN_LISTENERS = env_int("ALBUM_MID_TAIL_MIN_LISTENERS", 10000)
ALBUM_MAX_TAGS = env_int("ALBUM_MAX_TAGS", 10)
ALBUM_COVER_SIZE = env_int("ALBUM_COVER_SIZE", 500)
if ALBUM_COVER_SIZE not in (250, 500, 1200):
    raise ImproperlyConfigured("ALBUM_COVER_SIZE must be 250, 500 or 1200")
# The mid-tail band (fewer listeners) only appears deep in each tag's list: on page 1 the median
# album has about 1,000,000 listeners, on page 8 about 80,000, and on page 30 about 36,000.
ALBUM_MID_TAIL_START_PAGE = env_int("ALBUM_MID_TAIL_START_PAGE", 20)
# The most albums the mid-tail search checks (one Last.fm lookup each) before it gives up.
ALBUM_MID_TAIL_MAX_SCAN = env_int("ALBUM_MID_TAIL_MAX_SCAN", 1000)
# Wikipedia intros are fetched in batches; the API allows at most 20 titles per request.
ALBUM_BATCH_SIZE = env_int("ALBUM_BATCH_SIZE", 20, maximum=20)
# MusicBrainz and Wikimedia require a User-Agent that says how to reach you: an email or a URL.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
# MusicBrainz allows about one request a second and blocks clients that go faster.
MUSICBRAINZ_MIN_INTERVAL_SECONDS = env_float("MUSICBRAINZ_MIN_INTERVAL_SECONDS", 1.1, minimum=1.0)
WIKIMEDIA_REQUESTS_PER_SECOND = env_int("WIKIMEDIA_REQUESTS_PER_SECOND", 1)
COVERART_REQUESTS_PER_SECOND = env_int("COVERART_REQUESTS_PER_SECOND", 4)

# Search. Queries longer than the cap are rejected, not truncated, so their meaning never changes.
SEARCH_MAX_QUERY_LENGTH = env_int("SEARCH_MAX_QUERY_LENGTH", 200)
# Results in a single-type list and in a blended list; and per type when results are grouped.
SEARCH_RESULT_LIMIT = env_int("SEARCH_RESULT_LIMIT", 15)
SEARCH_GROUP_LIMIT = env_int("SEARCH_GROUP_LIMIT", 10)
# Candidates fetched per media type before the layout picks what to show.
SEARCH_CANDIDATES_PER_TYPE = env_int("SEARCH_CANDIDATES_PER_TYPE", 50)
# In a blended list, the slots every media type with matches is guaranteed (0 turns this off).
SEARCH_BLEND_MIN_SLOTS = env_int("SEARCH_BLEND_MIN_SLOTS", 2, minimum=0)

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
MID_TAIL_PERCENT = env_int("MID_TAIL_PERCENT", 10, minimum=0, maximum=100)
CATALOG_TARGET_PER_TYPE = env_int("CATALOG_TARGET_PER_TYPE", 2000)
# Cap for sample runs (for example 50). 0 means use CATALOG_TARGET_PER_TYPE.
INGEST_LIMIT = env_int("INGEST_LIMIT", 0, minimum=0)

# Logs go to the console (Docker collects them). Job progress from the worker is INFO. Query text
# is never logged.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "").strip().upper() or "INFO"
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    raise ImproperlyConfigured("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    # Printed twice on every start-up; the worker's job messages are the useful ones.
    "loggers": {"procrastinate.blueprints": {"level": "WARNING"}},
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
