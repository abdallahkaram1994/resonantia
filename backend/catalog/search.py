from collections.abc import Sequence
from dataclasses import dataclass

from pgvector.django import CosineDistance

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
    media_types: Sequence[str],
    model: str,
    dim: int,
    limit: int,
) -> list[SearchHit]:
    """Nearest items by cosine distance, with every filter applied in SQL before ranking.

    Only vectors made by the same model and dimension as the query are compared.
    """
    rows = (
        Item.objects.filter(
            media_type__in=media_types,
            embedding__isnull=False,
            embedding_model=model,
            embedding_dim=dim,
        )
        .only("id", "media_type", "title", "release_year", "cover_url")
        .annotate(distance=CosineDistance("embedding", list(vector)))
        .order_by("distance", "id")[:limit]
    )
    return [SearchHit(item=row, score=1.0 - row.distance) for row in rows]
