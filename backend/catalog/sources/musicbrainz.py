import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from catalog.http import (
    HttpError,
    NetworkError,
    RetryPolicy,
    Transport,
    request_json,
    urllib_transport,
)
from catalog.ratelimit import Throttle
from catalog.sources.base import SourceRequestError, SourceUnavailable

BASE_URL = "https://musicbrainz.org/ws/2"

_MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_WIKIDATA_URL = re.compile(r"https?://(?:www\.)?wikidata\.org/wiki/(Q[1-9][0-9]{0,12})")
_DATE = re.compile(r"(\d{4})(?:-\d{2}){0,2}")
_TEXT_MAX = 500


def normalize_mbid(value: object) -> str | None:
    """A well-formed MusicBrainz id, lowercased, or None. Ids come from other services, so they
    are checked before they are put in a URL."""
    if not isinstance(value, str):
        return None
    mbid = value.strip().lower()
    return mbid if _MBID.fullmatch(mbid) else None


def parse_release_year(value: object) -> int | None:
    """MusicBrainz dates can be partial: "1997-05-21", "1997-05", "1997", or empty."""
    if not isinstance(value, str):
        return None
    match = _DATE.fullmatch(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    return year if 1900 <= year <= 2200 else None


def _text(value: object, max_length: int = _TEXT_MAX) -> str:
    return value.strip()[:max_length] if isinstance(value, str) else ""


def _artist_credit(credit: object) -> str:
    """ "Simon & Garfunkel" is two credited artists joined by " & "."""
    if not isinstance(credit, list):
        return ""
    parts = []
    for entry in credit:
        if isinstance(entry, dict):
            phrase = entry.get("joinphrase")
            # The join phrase keeps its own spaces (" & "), so it is not stripped.
            parts.append(
                _text(entry.get("name"), 200) + (phrase[:20] if isinstance(phrase, str) else "")
            )
    return " ".join("".join(parts).split())[:_TEXT_MAX]


def _wikidata_id(relations: object) -> str | None:
    if not isinstance(relations, list):
        return None
    for relation in relations:
        if not isinstance(relation, dict) or relation.get("type") != "wikidata":
            continue
        url = relation.get("url")
        resource = url.get("resource") if isinstance(url, dict) else None
        match = _WIKIDATA_URL.fullmatch(resource) if isinstance(resource, str) else None
        if match:
            return match.group(1)
    return None


@dataclass(frozen=True)
class ReleaseGroup:
    mbid: str
    title: str
    artist: str
    primary_type: str
    secondary_types: tuple[str, ...]
    release_year: int | None
    wikidata_id: str | None

    @property
    def is_studio_album(self) -> bool:
        """Primary type Album and no secondary type (so no live, compilation or soundtrack)."""
        return self.primary_type == "Album" and not self.secondary_types


class MusicBrainzClient:
    """Two lookups by id. Nothing here searches by title: an album that cannot be matched by id
    is dropped, never guessed. Only core data (CC0) is read; tags and genres are not."""

    def __init__(
        self,
        *,
        user_agent: str,
        throttle: Throttle,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        self._user_agent = user_agent
        self._throttle = throttle
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._base_url = base_url

    def __repr__(self) -> str:
        return "MusicBrainzClient()"

    def release_group_id(self, release_mbid: str) -> str | None:
        """The release-group a release belongs to. Last.fm returns release ids."""
        mbid = normalize_mbid(release_mbid)
        if mbid is None:
            return None
        data = self._get(f"release/{mbid}", {"inc": "release-groups", "fmt": "json"})
        group = data.get("release-group") if data else None
        return normalize_mbid(group.get("id")) if isinstance(group, dict) else None

    def release_group(self, release_group_mbid: str) -> ReleaseGroup | None:
        mbid = normalize_mbid(release_group_mbid)
        if mbid is None:
            return None
        data = self._get(f"release-group/{mbid}", {"inc": "artist-credits+url-rels", "fmt": "json"})
        if data is None:
            return None
        title = _text(data.get("title"))
        if not title:
            return None
        secondary = data.get("secondary-types")
        return ReleaseGroup(
            mbid=mbid,
            title=title,
            artist=_artist_credit(data.get("artist-credit")),
            primary_type=_text(data.get("primary-type"), 50),
            secondary_types=tuple(
                _text(t, 50) for t in secondary if isinstance(t, str) and t.strip()
            )
            if isinstance(secondary, list)
            else (),
            release_year=parse_release_year(data.get("first-release-date")),
            wikidata_id=_wikidata_id(data.get("relations")),
        )

    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any] | None:
        """The parsed JSON object, or None when MusicBrainz has no such id (404)."""
        self._throttle.wait()
        # "inc" values are joined with "+", which must stay literal, so build the query by hand.
        query = urlencode(params, safe="+")
        try:
            data = request_json(
                self._transport,
                "GET",
                f"{self._base_url}/{path}?{query}",
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            if error.status == 404:
                return None
            if error.status == 429 or error.status >= 500:
                raise SourceUnavailable(
                    f"MusicBrainz is unavailable or rate limiting (HTTP {error.status})"
                ) from error
            raise SourceRequestError(
                f"MusicBrainz rejected the request (HTTP {error.status})"
            ) from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach MusicBrainz") from error
        except ValueError as error:
            raise SourceUnavailable("MusicBrainz returned a response that is not JSON") from error
        if not isinstance(data, dict):
            raise SourceUnavailable("MusicBrainz returned an unexpected response")
        return data
