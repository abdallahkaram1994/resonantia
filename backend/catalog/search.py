from collections.abc import Sequence
from dataclasses import dataclass

from django.db.models import Q
from pgvector.django import CosineDistance

from catalog.filters import ActiveFilter, predicate_for
from catalog.models import Item


def normalize_query(raw: str) -> str:
    """Lowercase, trim, and collapse all whitespace runs to single spaces."""
    return " ".join(raw.split()).lower()


@dataclass(frozen=True)
class SearchHit:
    item: Item
    # Cosine similarity. Scores compress into a narrow band, so use them for ordering only.
    score: float


def retrieve(
    vector: Sequence[float],
    *,
    media_type: str,
    keep: Q | None = None,
    model: str,
    dim: int,
    limit: int,
) -> list[SearchHit]:
    """Nearest items of one media type by cosine distance. `keep` (the filters for that type) is
    applied in SQL before ranking.

    Only vectors made by the same model and dimension as the query are compared.
    """
    rows = Item.objects.filter(
        media_type=media_type,
        embedding__isnull=False,
        embedding_model=model,
        embedding_dim=dim,
    )
    if keep is not None:
        rows = rows.filter(keep)
    rows = (
        rows.only("id", "media_type", "title", "release_year", "cover_url")
        .annotate(distance=CosineDistance("embedding", list(vector)))
        .order_by("distance", "id")[:limit]
    )
    return [SearchHit(item=row, score=1.0 - row.distance) for row in rows]


def retrieve_by_type(
    vector: Sequence[float],
    *,
    media_types: Sequence[str],
    filters: Sequence[ActiveFilter],
    model: str,
    dim: int,
    limit: int,
) -> dict[str, list[SearchHit]]:
    """One candidate pool per enabled type, each narrowed only by the filters that apply to that
    type, so a filter scoped to one type can never remove another type's items."""
    return {
        media_type: retrieve(
            vector,
            media_type=media_type,
            keep=predicate_for(media_type, filters),
            model=model,
            dim=dim,
            limit=limit,
        )
        for media_type in media_types
    }
