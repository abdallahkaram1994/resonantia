from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from catalog.ratelimit import Throttle
from catalog.sources.base import FilmSource
from catalog.sources.tmdb import TmdbFilmSource


def get_film_source() -> FilmSource:
    if not settings.TMDB_READ_ACCESS_TOKEN:
        raise ImproperlyConfigured("TMDB_READ_ACCESS_TOKEN is not set")
    return TmdbFilmSource(
        token=settings.TMDB_READ_ACCESS_TOKEN,
        throttle=Throttle(1.0 / settings.TMDB_REQUESTS_PER_SECOND),
        image_base_url=settings.TMDB_IMAGE_BASE_URL,
        min_vote_count=settings.FILM_MIN_VOTE_COUNT,
        mid_tail_min_vote_count=settings.FILM_MID_TAIL_MIN_VOTE_COUNT,
    )
