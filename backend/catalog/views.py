import logging
import math

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from catalog.embedding.base import EmbeddingError, EmbeddingRateLimited
from catalog.embedding.factory import get_embedder
from catalog.filters import FilterError, parse_filters, parse_media_types
from catalog.models import MediaType
from catalog.search import normalize_query, retrieve_by_type

logger = logging.getLogger(__name__)

# Types searched when the request does not choose (`types=`). This becomes all three when the
# hybrid layout lands (M4 slice 3): until then a mixed list would be ordered by raw scores, which
# are not comparable across types.
DEFAULT_MEDIA_TYPES = (MediaType.FILM,)


def _unavailable(retry_after: float | None = None) -> Response:
    response = Response(
        {"detail": "Search is temporarily unavailable. Please try again later."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    if retry_after is not None and retry_after > 0:
        response["Retry-After"] = str(math.ceil(retry_after))
    return response


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
        vector = embedder.embed([query], "query")[0]
    except ImproperlyConfigured as error:
        logger.error("Search is misconfigured: %s", error)
        return _unavailable()
    except EmbeddingRateLimited as error:
        logger.warning("Embedding provider is rate limiting: %s", error)
        return _unavailable(error.retry_after)
    except EmbeddingError as error:
        logger.warning("Embedding failed during search (%s): %s", type(error).__name__, error)
        return _unavailable()

    limit = settings.SEARCH_RESULT_LIMIT
    pools = retrieve_by_type(
        vector,
        media_types=media_types,
        filters=filters,
        model=embedder.model,
        dim=embedder.dimensions,
        limit=limit,
    )
    # Interim: one list ordered by raw score. The layout slice replaces this merge.
    hits = sorted(
        (hit for pool in pools.values() for hit in pool), key=lambda hit: (-hit.score, hit.item.id)
    )[:limit]
    return Response(
        {
            "query": query,
            "results": [
                {
                    "id": hit.item.id,
                    "media_type": hit.item.media_type,
                    "title": hit.item.title,
                    "release_year": hit.item.release_year,
                    "cover_url": hit.item.cover_url,
                    "score": round(hit.score, 4),
                }
                for hit in hits
            ],
        }
    )
