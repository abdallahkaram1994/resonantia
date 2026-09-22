"""How candidates from several media types become one search response (SPEC section 7.3).

- One type enabled: a single ranked list.
- Several types enabled and the query names one: grouped, the named type first.
- Several types enabled and no type named: one blended list.

Similarity scores from different media types are not comparable (a query sits at a different
distance from films than from albums), so a blended list never sorts raw scores across types.
It orders hits by their standout score, how far above its own type's average a hit sits, and
guarantees every type that has matches a minimum number of slots, so no type is starved.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from catalog.models import MediaType
from catalog.search import SearchHit

SINGLE = "single"
GROUPED = "grouped"
BLENDED = "blended"


@dataclass(frozen=True)
class Layout:
    kind: str
    # The ranked list, for `single` and `blended`.
    hits: list[SearchHit] = field(default_factory=list)
    # One (media type, hits) pair per enabled type, for `grouped`. A type with no matches stays in
    # the list, empty, so the page can say so.
    groups: list[tuple[str, list[SearchHit]]] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


def blend(
    pools: Mapping[str, Sequence[SearchHit]], *, limit: int, min_slots: int
) -> list[SearchHit]:
    """One list of at most `limit` hits. Each type that has matches first gets its best
    `min_slots` (fewer if the list is too short for that), then the remaining slots go to the
    highest standout scores, whichever type they belong to."""
    pools = {media_type: pool for media_type, pool in pools.items() if pool}
    if not pools:
        return []

    def rank(hit: SearchHit) -> tuple[float, float, int]:
        # Raw score and id only break ties.
        return (-hit.standout, -hit.score, hit.item.id)

    reserved = min(min_slots, limit // len(pools))
    chosen: list[SearchHit] = []
    rest: list[SearchHit] = []
    for pool in pools.values():
        chosen += pool[:reserved]
        rest += pool[reserved:]
    rest.sort(key=rank)
    chosen += rest[: max(0, limit - len(chosen))]
    chosen.sort(key=rank)
    return chosen


def build_layout(
    pools: Mapping[str, Sequence[SearchHit]],
    *,
    hint: str | None = None,
    result_limit: int,
    group_limit: int,
    min_slots: int,
) -> Layout:
    """Lay out the candidate pools of the enabled media types (the keys of `pools`).

    `hint` is the media type the query itself names, if any (the LLM parse supplies it in M5).
    A hint for a type that is switched off is ignored with a notice: the toggle wins.
    """
    enabled = [t for t in MediaType.values if t in pools]
    notices: list[str] = []
    named: str | None = None
    if hint is not None and hint in MediaType.values:
        if hint in enabled:
            named = hint
        else:
            label = MediaType(hint).label.lower()
            notices.append(f"Your search mentions {label}s, but {label}s are switched off.")

    if len(enabled) == 1:
        return Layout(SINGLE, hits=list(pools[enabled[0]][:result_limit]), notices=notices)

    if named is not None:
        order = [named] + [t for t in enabled if t != named]
        groups = [(t, list(pools[t][:group_limit])) for t in order]
        return Layout(GROUPED, groups=groups, notices=notices)

    hits = blend(pools, limit=result_limit, min_slots=min_slots)
    return Layout(BLENDED, hits=hits, notices=notices)
