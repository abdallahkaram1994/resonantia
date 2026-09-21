from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from catalog.ledger import DbLedger
from catalog.ratelimit import Throttle
from catalog.sources.albums import DATA_DIR, AlbumSource, load_lines
from catalog.sources.base import FilmSource, ItemSource
from catalog.sources.coverart import CoverArtArchive
from catalog.sources.igdb import IgdbGameSource
from catalog.sources.lastfm import LastFmClient
from catalog.sources.musicbrainz import MusicBrainzClient
from catalog.sources.tmdb import TmdbFilmSource
from catalog.sources.useragent import build_user_agent
from catalog.sources.wikipedia import WikipediaClient


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


def get_album_source(
    *, retry_skipped: bool = False, heartbeat: Callable[[str], None] | None = None
) -> ItemSource:
    if not settings.LASTFM_API_KEY:
        raise ImproperlyConfigured("LASTFM_API_KEY is not set")
    if not settings.CONTACT_EMAIL:
        raise ImproperlyConfigured(
            "CONTACT_EMAIL is not set (MusicBrainz and Wikimedia require a way to contact you)"
        )
    try:
        user_agent = build_user_agent(settings.CONTACT_EMAIL)
    except ValueError as error:
        raise ImproperlyConfigured(str(error)) from error
    return AlbumSource(
        lastfm=LastFmClient(
            api_key=settings.LASTFM_API_KEY,
            user_agent=user_agent,
            throttle=Throttle(1.0 / settings.LASTFM_REQUESTS_PER_SECOND),
            blocklist=load_lines(DATA_DIR / "lastfm_tag_blocklist.txt"),
            max_tags=settings.ALBUM_MAX_TAGS,
        ),
        musicbrainz=MusicBrainzClient(
            user_agent=user_agent,
            throttle=Throttle(settings.MUSICBRAINZ_MIN_INTERVAL_SECONDS),
        ),
        coverart=CoverArtArchive(
            user_agent=user_agent,
            throttle=Throttle(1.0 / settings.COVERART_REQUESTS_PER_SECOND),
            size=settings.ALBUM_COVER_SIZE,
        ),
        wikipedia=WikipediaClient(
            user_agent=user_agent,
            throttle=Throttle(1.0 / settings.WIKIMEDIA_REQUESTS_PER_SECOND),
        ),
        ledger=DbLedger(retry_skipped=retry_skipped),
        tags=load_lines(DATA_DIR / "lastfm_tags.txt"),
        min_listeners=settings.ALBUM_MIN_LISTENERS,
        mid_tail_min_listeners=settings.ALBUM_MID_TAIL_MIN_LISTENERS,
        batch_size=settings.ALBUM_BATCH_SIZE,
        mid_tail_start_page=settings.ALBUM_MID_TAIL_START_PAGE,
        mid_tail_max_scan=settings.ALBUM_MID_TAIL_MAX_SCAN,
        heartbeat=heartbeat,
    )
