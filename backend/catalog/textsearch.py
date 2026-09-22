"""Postgres full-text search: the fallback used only when the embedding provider is unavailable
(SPEC section 7.5). It matches words, not vibes, and is not meant to compete with vibe search on
quality — it exists so a visitor still gets useful results when the vibe search cannot run.

Query words are reduced to plain `[a-z0-9]` tokens and OR-ed together (not AND-ed, so a multi-word
vibe phrase still finds partial matches), then ranked with `ts_rank`. Postgres' cover-density
variant (`ts_rank_cd`) was tried first, since it is usually the better choice, but for an OR query
it rewards a document that just repeats one matched word over one that matches several different
words — tested directly against Postgres, a document with "rain" four times outranked one with
both "rain" and "night" once each. Plain `ts_rank` does not have that problem. The GIN index on
`combined_text` (see `Item.Meta.indexes`) backs the match itself; English stemming only.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from functools import reduce

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q

from catalog.filters import ActiveFilter, predicate_for
from catalog.models import Item
from catalog.search import SearchHit

CONFIG = "english"
_TOKEN = re.compile(r"[a-z0-9]+")
_MIN_SPREAD = 1e-6


def tokenize(query: str) -> list[str]:
    """The query's words, lowercase `[a-z0-9]` only. Anything else — punctuation, other scripts,
    control characters — is dropped rather than handed to Postgres' text-search parser, whose own
    query syntax (quotes, `-`, `OR`) a raw query should never be able to trigger."""
    return _TOKEN.findall(query.lower())


def _search_query(tokens: Sequence[str]) -> SearchQuery:
    return reduce(lambda a, b: a | b, (SearchQuery(token, config=CONFIG) for token in tokens))


def text_search(
    tokens: Sequence[str], *, media_type: str, keep: Q | None, limit: int
) -> list[SearchHit]:
    """The best-ranked items of one media type whose combined text contains at least one of the
    tokens. Empty when there are no usable tokens (for example a query of only punctuation or
    emoji), rather than matching everything."""
    if not tokens:
        return []
    search_query = _search_query(tokens)
    vector = SearchVector("combined_text", config=CONFIG)
    rows = Item.objects.filter(media_type=media_type)
    if keep is not None:
        rows = rows.filter(keep)
    rows = (
        rows.annotate(search=vector, rank=SearchRank(vector, search_query))
        .filter(search=search_query)
        .only("id", "media_type", "title", "release_year", "cover_url")
        .order_by("-rank", "id")[:limit]
    )
    return [SearchHit(item=row, score=round(float(row.rank), 4)) for row in rows]


def _scale_to_standout(hits: list[SearchHit]) -> list[SearchHit]:
    """Each hit's rank scaled to 0 (the pool's weakest match) .. 1 (its best), so ranks from
    different media types can sit in one blended list (`catalog.layout.blend`).

    Vector search instead scores standing against the whole catalog's average (SPEC section 7.4),
    because a dense catalog makes a pool's own best-to-worst spread misleading. A full-text pool is
    the opposite: mostly exact non-matches elsewhere, so scaling within the matched pool alone is a
    reasonable, and far cheaper, stand-in here.
    """
    if not hits:
        return hits
    scores = [hit.score for hit in hits]
    low, high = min(scores), max(scores)
    if high - low < _MIN_SPREAD:
        return [replace(hit, standout=1.0) for hit in hits]
    return [replace(hit, standout=(hit.score - low) / (high - low)) for hit in hits]


def text_retrieve_by_type(
    query: str, *, media_types: Sequence[str], filters: Sequence[ActiveFilter], limit: int
) -> dict[str, list[SearchHit]]:
    """One candidate pool per enabled type, each narrowed only by the filters that apply to that
    type, exactly like vector retrieval, so a type-scoped filter still can never affect another
    type's rows."""
    tokens = tokenize(query)
    return {
        media_type: _scale_to_standout(
            text_search(
                tokens,
                media_type=media_type,
                keep=predicate_for(media_type, filters),
                limit=limit,
            )
        )
        for media_type in media_types
    }
