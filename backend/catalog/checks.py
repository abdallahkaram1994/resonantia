from django.conf import settings
from django.core import checks

from catalog.models import EMBEDDING_DIMENSIONS


@checks.register()
def embedding_dimension_matches_column(app_configs, **kwargs):
    if settings.EMBEDDING_DIM != EMBEDDING_DIMENSIONS:
        return [
            checks.Error(
                f"EMBEDDING_DIM is {settings.EMBEDDING_DIM} but the Item.embedding column is "
                f"{EMBEDDING_DIMENSIONS} wide. Changing it needs a migration and a full re-embed.",
                id="catalog.E001",
            )
        ]
    return []


@checks.register()
def mid_tail_band_is_below_the_popularity_threshold(app_configs, **kwargs):
    errors = []
    if settings.FILM_MID_TAIL_MIN_VOTE_COUNT >= settings.FILM_MIN_VOTE_COUNT:
        errors.append(
            checks.Error(
                "FILM_MID_TAIL_MIN_VOTE_COUNT must be lower than FILM_MIN_VOTE_COUNT, "
                "otherwise the mid-tail band is empty.",
                id="catalog.E002",
            )
        )
    if settings.GAME_MID_TAIL_MIN_RATING_COUNT >= settings.GAME_MIN_RATING_COUNT:
        errors.append(
            checks.Error(
                "GAME_MID_TAIL_MIN_RATING_COUNT must be lower than GAME_MIN_RATING_COUNT, "
                "otherwise the mid-tail band is empty.",
                id="catalog.E003",
            )
        )
    if settings.ALBUM_MID_TAIL_MIN_LISTENERS >= settings.ALBUM_MIN_LISTENERS:
        errors.append(
            checks.Error(
                "ALBUM_MID_TAIL_MIN_LISTENERS must be lower than ALBUM_MIN_LISTENERS, "
                "otherwise the mid-tail band is empty.",
                id="catalog.E004",
            )
        )
    return errors
