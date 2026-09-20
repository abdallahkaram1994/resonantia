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
