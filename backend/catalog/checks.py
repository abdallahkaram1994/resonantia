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
    if settings.FILM_MID_TAIL_MIN_VOTE_COUNT >= settings.FILM_MIN_VOTE_COUNT:
        return [
            checks.Error(
                "FILM_MID_TAIL_MIN_VOTE_COUNT must be lower than FILM_MIN_VOTE_COUNT, "
                "otherwise the mid-tail band is empty.",
                id="catalog.E002",
            )
        ]
    return []
