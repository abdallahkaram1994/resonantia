"""Search filters (SPEC section 7.2).

Media type toggles are hard constraints, parsed by `parse_media_types`. Every other filter is a
class in the registry that says which media types it `applies_to` and turns its request value into
a SQL predicate. Retrieval asks for one predicate per media type, so a filter scoped to one type
cannot touch another type's rows, and a type nothing applies to passes through unfiltered.

Adding a filter is one class here plus one entry in `FILTERS`.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from django.db.models import Q

from catalog.models import MediaType

MIN_YEAR = 1800
MAX_YEAR = 2200
MAX_ERA_RANGES = 10
_ERA = re.compile(r"([0-9]{4})-([0-9]{4})")


class FilterError(ValueError):
    """The request's filter values are unusable. The message is safe to show to a visitor and
    never repeats what was sent."""


class SearchFilter(Protocol):
    name: str
    # The media types this filter narrows. Others are left exactly as they are.
    applies_to: frozenset[str]

    def parse(self, params: Mapping[str, str]) -> Any | None:
        """The filter's value from the request, or None when it is not in use. Raises
        FilterError for a value that cannot be used."""
        ...

    def predicate(self, value: Any) -> Q:
        """The rows to keep, for a value returned by `parse`."""
        ...


class EraFilter:
    """Decade chips: `eras=1980-1989,1990-1999`, ranges of release years OR-ed together.

    A row with no release year matches no range, so it is dropped while this filter is active and
    kept while it is not.
    """

    name = "eras"
    applies_to = frozenset(MediaType.values)

    def parse(self, params: Mapping[str, str]) -> tuple[tuple[int, int], ...] | None:
        raw = params.get(self.name, "").strip()
        if not raw:
            return None
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) > MAX_ERA_RANGES:
            raise FilterError(f"Choose at most {MAX_ERA_RANGES} eras.")
        ranges: list[tuple[int, int]] = []
        for part in parts:
            match = _ERA.fullmatch(part)
            if match is None:
                raise FilterError("Eras must look like 1980-1989, separated by commas.")
            start, end = int(match[1]), int(match[2])
            if start > end or start < MIN_YEAR or end > MAX_YEAR:
                raise FilterError(
                    f"Each era must run from an earlier to a later year between {MIN_YEAR} "
                    f"and {MAX_YEAR}."
                )
            ranges.append((start, end))
        return tuple(dict.fromkeys(ranges))

    def predicate(self, value: tuple[tuple[int, int], ...]) -> Q:
        keep = Q()
        for start, end in value:
            keep |= Q(release_year__gte=start, release_year__lte=end)
        return keep


FILTERS: tuple[SearchFilter, ...] = (EraFilter(),)


@dataclass(frozen=True)
class ActiveFilter:
    filter: SearchFilter
    value: Any


def parse_filters(
    params: Mapping[str, str], registry: Sequence[SearchFilter] = FILTERS
) -> list[ActiveFilter]:
    """The filters the request switches on. Raises FilterError for an unusable value."""
    active = []
    for search_filter in registry:
        value = search_filter.parse(params)
        if value is not None:
            active.append(ActiveFilter(search_filter, value))
    return active


def predicate_for(media_type: str, active: Sequence[ActiveFilter]) -> Q:
    """Every active filter that applies to `media_type`, all of which must hold. Empty (keep
    everything) when none does."""
    keep = Q()
    for item in active:
        if media_type in item.filter.applies_to:
            keep &= item.filter.predicate(item.value)
    return keep


def parse_media_types(params: Mapping[str, str], default: Sequence[str]) -> tuple[str, ...]:
    """The media types switched on: `types=film,game`, or `default` when the parameter is absent.
    Always returned in the catalog's own order, without repeats."""
    raw = params.get("types")
    if raw is None:
        return tuple(default)
    names = {name.strip().lower() for name in raw.split(",") if name.strip()}
    if not names:
        raise FilterError("Choose at least one media type.")
    if not names <= set(MediaType.values):
        raise FilterError(f"Media types must be from: {', '.join(MediaType.values)}.")
    return tuple(media_type for media_type in MediaType.values if media_type in names)
