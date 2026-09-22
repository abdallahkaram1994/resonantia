import logging
import math

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from catalog.detail import item_detail as build_item_detail
from catalog.embedding.base import EmbeddingError, EmbeddingRateLimited
from catalog.embedding.factory import get_embedder
from catalog.filters import FilterError, parse_filters, parse_media_types
from catalog.layout import GROUPED, build_layout
from catalog.models import Item, MediaType
from catalog.search import (
    SearchHit,
    embed_query,
    normalize_query,
    retrieve_by_type,
    similar_items,
)

logger = logging.getLogger(__name__)

# Types searched when the request does not choose (`types=`): all of them.
DEFAULT_MEDIA_TYPES = tuple(MediaType.values)


def _unavailable(retry_after: float | None = None) -> Response:
    response = Response(
        {"detail": "Search is temporarily unavailable. Please try again later."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    if retry_after is not None and retry_after > 0:
        response["Retry-After"] = str(math.ceil(retry_after))
    return response


def _result(hit: SearchHit) -> dict[str, object]:
    return {
        "id": hit.item.id,
        "media_type": hit.item.media_type,
        "title": hit.item.title,
        "release_year": hit.item.release_year,
        "cover_url": hit.item.cover_url,
        "score": round(hit.score, 4),
    }


@api_view(["GET"])
def search(request: Request) -> Response:
    query = normalize_query(request.query_params.get("q", ""))
    if not query:
        return Response(
            {"detail": "Provide a search query in the 'q' parameter."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    max_length = settings.SEARCH_MAX_QUERY_LENGTH
    if len(query) > max_length:
        return Response(
            {"detail": f"Query is too long (maximum {max_length} characters)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Bad filter values are refused before the embedder is called, so they cost no quota.
    try:
        media_types = parse_media_types(request.query_params, DEFAULT_MEDIA_TYPES)
        filters = parse_filters(request.query_params)
    except FilterError as error:
        return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    # Failures are logged without the query text: searches are anonymous and stay private.
    try:
        embedder = get_embedder()
        vector = embed_query(embedder, query)
    except ImproperlyConfigured as error:
        logger.error("Search is misconfigured: %s", error)
        return _unavailable()
    except EmbeddingRateLimited as error:
        logger.warning("Embedding provider is rate limiting: %s", error)
        return _unavailable(error.retry_after)
    except EmbeddingError as error:
        logger.warning("Embedding failed during search (%s): %s", type(error).__name__, error)
        return _unavailable()

    pools = retrieve_by_type(
        vector,
        media_types=media_types,
        filters=filters,
        model=embedder.model,
        dim=embedder.dimensions,
        limit=settings.SEARCH_CANDIDATES_PER_TYPE,
    )
    # No media type hint yet: the LLM parse that names one arrives in M5.
    layout = build_layout(
        pools,
        hint=None,
        result_limit=settings.SEARCH_RESULT_LIMIT,
        group_limit=settings.SEARCH_GROUP_LIMIT,
        min_slots=settings.SEARCH_BLEND_MIN_SLOTS,
    )
    body: dict[str, object] = {
        "query": query,
        "layout": layout.kind,
        "mode": "vibe",
        "notices": layout.notices,
    }
    if layout.kind == GROUPED:
        body["groups"] = [
            {"media_type": media_type, "results": [_result(hit) for hit in hits]}
            for media_type, hits in layout.groups
        ]
    else:
        body["results"] = [_result(hit) for hit in layout.hits]
    return Response(body)


@api_view(["GET"])
def item_detail(request: Request, item_id: int) -> Response:
    item = get_object_or_404(Item, id=item_id)
    return Response(build_item_detail(item))


@api_view(["GET"])
def item_similar(request: Request, item_id: int) -> Response:
    item = get_object_or_404(Item, id=item_id)
    hits = similar_items(item, limit=settings.ITEM_SIMILAR_LIMIT)
    groups: dict[str, list[SearchHit]] = {}
    for hit in hits:
        groups.setdefault(hit.item.media_type, []).append(hit)
    return Response(
        {
            "groups": [
                {"media_type": media_type, "results": [_result(hit) for hit in groups[media_type]]}
                for media_type in MediaType.values
                if media_type in groups
            ]
        }
    )
