import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from itertools import count
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
from catalog.models import MediaType
from catalog.ratelimit import Throttle
from catalog.sources.base import ItemRecord, ScoreRecord, SourceRequestError, SourceUnavailable

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.igdb.com/v4/games"
IMAGE_URL = "https://images.igdb.com/igdb/image/upload"
SOURCE = "igdb"
PAGE_SIZE = 100

# Main games only (game_type 0): no DLC, expansions, bundles, remakes or remasters. The older
# `category` field is deprecated and returns nothing. version_parent excludes editions.
_MAIN_GAMES = "game_type = 0 & version_parent = null"
_FIELDS = (
    "name, summary, first_release_date, genres.name, themes.name, keywords.name, "
    "cover.image_id, total_rating, total_rating_count"
)
_IMAGE_ID = re.compile(r"[a-z0-9]{3,40}")
_COVER_SIZE = re.compile(r"t_[a-z0-9_]{1,30}")
_TITLE_MAX = 500


def _text(value: object, max_length: int | None = None) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:max_length] if max_length else text


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _names(items: object) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    names = (_text(item.get("name"), 200) for item in items if isinstance(item, dict))
    return tuple(name for name in names if name)


def _year(timestamp: object) -> int | None:
    seconds = _int(timestamp)
    if seconds is None:
        return None
    try:
        year = datetime.fromtimestamp(seconds, UTC).year
    except (OverflowError, OSError, ValueError):
        return None
    return year if 1950 <= year <= 2200 else None


class IgdbGameSource:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        throttle: Throttle,
        cover_size: str,
        min_rating_count: int,
        mid_tail_min_rating_count: int,
        max_keywords: int,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not _COVER_SIZE.fullmatch(cover_size):
            raise ValueError(f"Invalid IGDB cover size: {cover_size!r}")
        self._client_id = client_id
        self._client_secret = client_secret
        self._throttle = throttle
        self._cover_size = cover_size
        self._min_rating_count = min_rating_count
        self._mid_tail_min_rating_count = mid_tail_min_rating_count
        self._max_keywords = max_keywords
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None

    def __repr__(self) -> str:
        return f"IgdbGameSource(min_rating_count={self._min_rating_count})"

    def popular(self) -> Iterator[ItemRecord]:
        return self._games(f"total_rating_count >= {self._min_rating_count}")

    def mid_tail(self) -> Iterator[ItemRecord]:
        return self._games(
            f"total_rating_count >= {self._mid_tail_min_rating_count} "
            f"& total_rating_count < {self._min_rating_count}"
        )

    def _games(self, rating_filter: str) -> Iterator[ItemRecord]:
        for offset in count(0, PAGE_SIZE):
            query = (
                f"fields {_FIELDS}; where {_MAIN_GAMES} & {rating_filter}; "
                f"sort total_rating_count desc; limit {PAGE_SIZE}; offset {offset};"
            )
            rows = self._query(query)
            for row in rows:
                record = self._parse(row)
                if record is not None:
                    yield record
            if len(rows) < PAGE_SIZE:
                return

    def _parse(self, row: object) -> ItemRecord | None:
        if not isinstance(row, dict):
            return None
        game_id = _int(row.get("id"))
        title = _text(row.get("name"), _TITLE_MAX)
        if game_id is None or not title:
            return None

        genres = _names(row.get("genres"))
        themes = _names(row.get("themes"))
        keywords = _names(row.get("keywords"))[: self._max_keywords]
        # Themes are clean mood words; the capped keyword list adds detail without drowning them.
        tags = tuple(dict.fromkeys((*themes, *keywords)))

        cover = row.get("cover")
        image_id = cover.get("image_id") if isinstance(cover, dict) else None
        cover_url = (
            f"{IMAGE_URL}/{self._cover_size}/{image_id}.jpg"
            if isinstance(image_id, str) and _IMAGE_ID.fullmatch(image_id)
            else ""
        )

        rating, rating_count = _number(row.get("total_rating")), _int(row.get("total_rating_count"))
        return ItemRecord(
            media_type=MediaType.GAME,
            source=SOURCE,
            source_id=str(game_id),
            title=title,
            release_year=_year(row.get("first_release_date")),
            summary=_text(row.get("summary")),
            genres=genres,
            keywords=tags,
            cover_url=cover_url,
            details={
                "genres": list(genres),
                "themes": list(themes),
                "keywords": list(keywords),
            },
            fetched_at=self._clock(),
            score=(
                ScoreRecord(SOURCE, rating, rating_count)
                if rating is not None and rating_count is not None
                else None
            ),
        )

    def _access_token(self, *, refresh: bool = False) -> str:
        if self._token is not None and not refresh:
            return self._token
        # Credentials go in the request body, never in the URL, so they stay out of logs.
        form = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            }
        ).encode()
        try:
            data = request_json(
                self._transport,
                "POST",
                TOKEN_URL,
                data=form,
                content_type="application/x-www-form-urlencoded",
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            if error.status in (400, 401, 403):
                raise SourceRequestError(
                    f"Twitch rejected the credentials (HTTP {error.status}). "
                    "Check TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET."
                ) from error
            raise SourceUnavailable(f"Twitch sign-in failed (HTTP {error.status})") from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach Twitch") from error
        except ValueError as error:
            raise SourceUnavailable("Twitch returned a response that is not JSON") from error
        token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise SourceUnavailable("Twitch did not return an access token")
        self._token = token
        return token

    def _query(self, query: str) -> list[Any]:
        for attempt in range(2):
            token = self._access_token(refresh=attempt == 1)
            self._throttle.wait()
            try:
                data = request_json(
                    self._transport,
                    "POST",
                    API_URL,
                    headers={"Client-ID": self._client_id, "Authorization": f"Bearer {token}"},
                    data=query.encode(),
                    content_type="text/plain",
                    timeout=self._timeout,
                    retry=self._retry,
                    sleep=self._sleep,
                )
            except HttpError as error:
                if error.status == 401 and attempt == 0:
                    continue  # the token may have expired: fetch a new one once
                raise self._map_http_error(error) from error
            except NetworkError as error:
                raise SourceUnavailable("Could not reach IGDB") from error
            except ValueError as error:
                raise SourceUnavailable("IGDB returned a response that is not JSON") from error
            if not isinstance(data, list):
                raise SourceUnavailable("IGDB returned an unexpected response")
            return data
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _map_http_error(error: HttpError) -> Exception:
        if error.status == 429 or error.status >= 500:
            return SourceUnavailable(f"IGDB is unavailable or rate limiting (HTTP {error.status})")
        message = ""
        try:
            body = json.loads(error.response.body)
            if isinstance(body, dict) and isinstance(body.get("message"), str):
                message = f": {body['message'][:200]}"
        except ValueError:
            pass
        hint = " Check the Twitch credentials." if error.status in (401, 403) else ""
        return SourceRequestError(
            f"IGDB rejected the request (HTTP {error.status}{message}).{hint}"
        )
