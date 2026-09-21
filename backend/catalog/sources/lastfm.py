import json
import time
from collections.abc import Callable, Collection, Mapping
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
from catalog.sources.musicbrainz import normalize_mbid

API_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 50
_TAG_MAX = 50

# Last.fm error codes worth telling apart. The rest are treated as rejected requests.
_NOT_FOUND = 6
_RATE_LIMIT = 29
_BAD_KEY = frozenset({10, 26})  # invalid or suspended API key
_TEMPORARY = frozenset({8, 11, 16})  # operation failed, service offline, temporary error


@dataclass(frozen=True)
class LastFmAlbum:
    name: str
    artist: str
    mbid: str | None  # a MusicBrainz release id; often missing
    url: str


@dataclass(frozen=True)
class LastFmAlbumInfo:
    tags: tuple[str, ...]
    listeners: int | None
    url: str


def _text(value: object, max_length: int = 500) -> str:
    return value.strip()[:max_length] if isinstance(value, str) else ""


def _as_list(value: object) -> list[Any]:
    """Last.fm's JSON gives a single result as an object instead of a one-item list."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _artist_name(value: object) -> str:
    return _text(value.get("name") if isinstance(value, dict) else value, 200)


class LastFmClient:
    """Album discovery by tag, and per-album tags and listener counts. Albums are only ever looked
    up by MusicBrainz id: a Last.fm entry without one is left to the caller to drop, never guessed
    by title. Last.fm data is for non-commercial use, credited to Last.fm."""

    def __init__(
        self,
        *,
        api_key: str,
        user_agent: str,
        throttle: Throttle,
        blocklist: Collection[str] = (),
        max_tags: int = 10,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = API_URL,
    ) -> None:
        self._api_key = api_key
        self._user_agent = user_agent
        self._throttle = throttle
        self._blocklist = frozenset(tag.strip().lower() for tag in blocklist)
        self._max_tags = max_tags
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._base_url = base_url

    def __repr__(self) -> str:
        return "LastFmClient()"

    def top_albums(self, tag: str, page: int) -> list[LastFmAlbum]:
        data = self._call(
            {"method": "tag.gettopalbums", "tag": tag, "page": str(page), "limit": str(PAGE_SIZE)}
        )
        albums = data.get("albums") if data else None
        found = []
        for entry in _as_list(albums.get("album") if isinstance(albums, dict) else None):
            if not isinstance(entry, dict):
                continue
            name = _text(entry.get("name"), 300)
            if not name:
                continue
            found.append(
                LastFmAlbum(
                    name=name,
                    artist=_artist_name(entry.get("artist")),
                    mbid=normalize_mbid(entry.get("mbid")),
                    url=_text(entry.get("url"), 500),
                )
            )
        return found

    def album_info(self, release_mbid: str) -> LastFmAlbumInfo | None:
        """Tags and listener count for a release, or None if Last.fm does not know it."""
        mbid = normalize_mbid(release_mbid)
        if mbid is None:
            return None
        data = self._call({"method": "album.getinfo", "mbid": mbid})
        if data is None:
            return None
        album = data.get("album")
        if not isinstance(album, dict):
            raise SourceUnavailable("Last.fm returned an unexpected response")
        tags = album.get("tags")
        raw_tags = _as_list(tags.get("tag") if isinstance(tags, dict) else None)
        own_names = {_text(album.get("name")).lower(), _artist_name(album.get("artist")).lower()}
        return LastFmAlbumInfo(
            tags=self._clean_tags(raw_tags, own_names),
            listeners=_count(album.get("listeners")),
            url=_text(album.get("url"), 500),
        )

    def _clean_tags(self, raw_tags: list[Any], own_names: set[str]) -> tuple[str, ...]:
        """Drop tags that describe the listener ("seen live") or just repeat the album or artist
        name, then keep the first few, in Last.fm's order (its most-applied tags first)."""
        kept: dict[str, str] = {}
        for entry in raw_tags:
            name = _text(entry.get("name") if isinstance(entry, dict) else entry, _TAG_MAX + 1)
            key = name.lower()
            if not name or len(name) > _TAG_MAX or key in self._blocklist or key in own_names:
                continue
            kept.setdefault(key, name)  # "Rock" and "rock" are one tag
        return tuple(kept.values())[: self._max_tags]

    def _call(self, params: Mapping[str, str]) -> dict[str, Any] | None:
        """The parsed JSON object, or None when Last.fm reports "not found"."""
        self._throttle.wait()
        # POST keeps the API key out of the URL.
        form = urlencode({**params, "api_key": self._api_key, "format": "json"}).encode()
        try:
            data = request_json(
                self._transport,
                "POST",
                self._base_url,
                headers={"User-Agent": self._user_agent},
                data=form,
                content_type="application/x-www-form-urlencoded",
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            # Last.fm can send its error object with a 4xx status, so look at the body first.
            body = self._error_body(error.response.body)
            if body is not None:
                return self._handle_error(body)
            if error.status == 429 or error.status >= 500:
                raise SourceUnavailable(
                    f"Last.fm is unavailable or rate limiting (HTTP {error.status})"
                ) from error
            raise SourceRequestError(
                f"Last.fm rejected the request (HTTP {error.status})"
            ) from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach Last.fm") from error
        except ValueError as error:
            raise SourceUnavailable("Last.fm returned a response that is not JSON") from error
        if not isinstance(data, dict):
            raise SourceUnavailable("Last.fm returned an unexpected response")
        if "error" in data:
            return self._handle_error(data)
        return data

    @staticmethod
    def _error_body(raw: bytes) -> dict[str, Any] | None:
        try:
            body = json.loads(raw)
        except ValueError:
            return None
        return body if isinstance(body, dict) and "error" in body else None

    @staticmethod
    def _handle_error(body: Mapping[str, Any]) -> None:
        code = body.get("error")
        message = _text(body.get("message"), 200)
        if code == _NOT_FOUND:
            return None
        if code == _RATE_LIMIT or code in _TEMPORARY:
            raise SourceUnavailable(f"Last.fm is unavailable or rate limiting (error {code})")
        if code in _BAD_KEY:
            raise SourceRequestError(
                f"Last.fm rejected the API key (error {code}). Check LASTFM_API_KEY."
            )
        raise SourceRequestError(f"Last.fm rejected the request (error {code}: {message})")
