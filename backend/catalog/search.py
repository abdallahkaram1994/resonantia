import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace

from django.db import DatabaseError, transaction
from django.db.models import Avg, Q, StdDev
from pgvector.django import CosineDistance

from catalog.embedding.base import Embedder
from catalog.filters import ActiveFilter, predicate_for
from catalog.models import Item, QueryEmbedding
from catalog.text import content_hash

logger = logging.getLogger(__name__)


def normalize_query(raw: str) -> str:
    """Lowercase, trim, and collapse all whitespace runs to single spaces."""
    return " ".join(raw.split()).lower()


def embed_query(embedder: Embedder, query: str) -> list[float]:
    """The embedding of a normalized query, from the cache when it was embedded before.

    Only successful embeddings are cached: an error from the provider passes through untouched and
    the next search tries again. A cache that cannot be written never fails the search.
    """
    key = {
        "text_hash": content_hash(query),
        "embedding_model": embedder.model,
        "embedding_dim": embedder.dimensions,
    }
    cached = QueryEmbedding.objects.filter(**key).values_list("embedding", flat=True).first()
    if cached is not None:
        return [float(value) for value in cached]

    vector = embedder.embed([query], "query")[0]
    try:
        # A concurrent search may have stored the same query a moment ago; that is not an error.
        with transaction.atomic():
            QueryEmbedding.objects.bulk_create(
                [QueryEmbedding(embedding=list(vector), **key)], ignore_conflicts=True
            )
    except DatabaseError as error:
        logger.warning("Could not cache a query embedding (%s)", type(error).__name__)
    return vector


@dataclass(frozen=True)
class SearchHit:
    item: Item
    # Cosine similarity. Scores compress into a narrow band, so use them for ordering only.
    score: float
    # How many standard deviations above the media type's own average similarity to this query.
    # Raw scores are not comparable across types (a query sits at a different distance from
    # films than from albums), but this is, so blended lists are ordered by it.
    standout: float = 0.0


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


# Below this spread a type's scores carry no signal (one item, or identical vectors).
_MIN_SPREAD = 1e-6


def standout_scores(
    vector: Sequence[float], *, media_type: str, model: str, dim: int
) -> tuple[float, float] | None:
    """The mean and spread of similarity between the query and every embedded item of one media
    type, or None when there are none. This is the type's whole catalog, never narrowed by
    filters, so a hit's standing does not change when the visitor changes a filter."""
    stats = Item.objects.filter(
        media_type=media_type,
        embedding__isnull=False,
        embedding_model=model,
        embedding_dim=dim,
    ).aggregate(
        mean=Avg(CosineDistance("embedding", list(vector))),
        spread=StdDev(CosineDistance("embedding", list(vector)), sample=False),
    )
    if stats["mean"] is None or stats["spread"] is None:
        return None
    return 1.0 - float(stats["mean"]), float(stats["spread"])


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
    type, so a filter scoped to one type can never remove another type's items. Every hit carries
    its standout score for the layout to compare across types."""
    pools: dict[str, list[SearchHit]] = {}
    for media_type in media_types:
        hits = retrieve(
            vector,
            media_type=media_type,
            keep=predicate_for(media_type, filters),
            model=model,
            dim=dim,
            limit=limit,
        )
        baseline = standout_scores(vector, media_type=media_type, model=model, dim=dim)
        if baseline is not None and baseline[1] >= _MIN_SPREAD:
            mean, spread = baseline
            hits = [replace(hit, standout=(hit.score - mean) / spread) for hit in hits]
        pools[media_type] = hits
    return pools
