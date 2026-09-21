from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from catalog.ratelimit import Throttle
from catalog.sources.base import FilmSource, ItemSource
from catalog.sources.igdb import IgdbGameSource
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


def get_game_source() -> ItemSource:
    if not settings.TWITCH_CLIENT_ID or not settings.TWITCH_CLIENT_SECRET:
        raise ImproperlyConfigured("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must both be set")
    return IgdbGameSource(
        client_id=settings.TWITCH_CLIENT_ID,
        client_secret=settings.TWITCH_CLIENT_SECRET,
        throttle=Throttle(1.0 / settings.IGDB_REQUESTS_PER_SECOND),
        cover_size=settings.IGDB_COVER_SIZE,
        min_rating_count=settings.GAME_MIN_RATING_COUNT,
        mid_tail_min_rating_count=settings.GAME_MID_TAIL_MIN_RATING_COUNT,
        max_keywords=settings.GAME_MAX_KEYWORDS,
    )
