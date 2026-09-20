import re
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
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
from catalog.sources.base import FilmRecord, SourceRequestError, SourceUnavailable

BASE_URL = "https://api.themoviedb.org/3"
MAX_DISCOVER_PAGES = 500
SOURCE = "tmdb"

_POSTER_PATH = re.compile(r"/[A-Za-z0-9_\-]+\.(?:jpg|jpeg|png|webp)")
_RELEASE_DATE = re.compile(r"(\d{4})-\d{2}-\d{2}")
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


def _year(release_date: object) -> int | None:
    match = _RELEASE_DATE.fullmatch(_text(release_date))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1870 <= year <= 2200 else None


def _names(items: object) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    names = (_text(item.get("name"), 200) for item in items if isinstance(item, dict))
    return tuple(name for name in names if name)


def _keyword_items(appended: object) -> object:
    """Keywords arrive as {"keywords": [...]}; also accept {"results": [...]} to be tolerant."""
    if not isinstance(appended, dict):
        return []
    for key in ("keywords", "results"):
        if isinstance(appended.get(key), list):
            return appended[key]
    return []


class TmdbFilmSource:
    def __init__(
        self,
        *,
        token: str,
        throttle: Throttle,
        image_base_url: str,
        min_vote_count: int,
        mid_tail_min_vote_count: int,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        base_url: str = BASE_URL,
    ) -> None:
        self._token = token
        self._throttle = throttle
        self._image_base_url = image_base_url.rstrip("/")
        self._min_vote_count = min_vote_count
        self._mid_tail_min_vote_count = mid_tail_min_vote_count
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._base_url = base_url

    def __repr__(self) -> str:
        return f"TmdbFilmSource(min_vote_count={self._min_vote_count})"

    def popular_films(self) -> Iterator[FilmRecord]:
        return self._films(
            {"sort_by": "vote_count.desc", "vote_count.gte": self._min_vote_count},
        )

    def mid_tail_films(self) -> Iterator[FilmRecord]:
        return self._films(
            {
                "sort_by": "popularity.desc",
                "vote_count.gte": self._mid_tail_min_vote_count,
                "vote_count.lte": self._min_vote_count - 1,
            },
        )

    def _films(self, discover_params: Mapping[str, object]) -> Iterator[FilmRecord]:
        seen: set[int] = set()
        for page in range(1, MAX_DISCOVER_PAGES + 1):
            data = self._get(
                "/discover/movie",
                {**discover_params, "include_adult": "false", "language": "en-US", "page": page},
            )
            results = data.get("results")
            if not isinstance(results, list):
                raise SourceUnavailable("TMDB discover response has no results list")
            for entry in results:
                movie_id = _int(entry.get("id")) if isinstance(entry, dict) else None
                if movie_id is None or movie_id in seen:
                    continue
                seen.add(movie_id)
                record = self._film(movie_id)
                if record is not None:
                    yield record
            total_pages = _int(data.get("total_pages")) or 0
            if page >= total_pages:
                return

    def _film(self, movie_id: int) -> FilmRecord | None:
        data = self._get(
            f"/movie/{movie_id}",
            {"append_to_response": "keywords", "language": "en-US"},
            allow_not_found=True,
        )
        if data is None:
            return None
        return self._parse_film(data)

    def _parse_film(self, movie: Mapping[str, Any]) -> FilmRecord | None:
        movie_id = _int(movie.get("id"))
        title = _text(movie.get("title"), _TITLE_MAX)
        if movie_id is None or not title:
            return None
        poster = movie.get("poster_path")
        cover_url = (
            f"{self._image_base_url}{poster}"
            if isinstance(poster, str) and _POSTER_PATH.fullmatch(poster)
            else ""
        )
        runtime = _int(movie.get("runtime"))
        return FilmRecord(
            source_id=movie_id,
            title=title,
            release_year=_year(movie.get("release_date")),
            overview=_text(movie.get("overview")),
            genres=_names(movie.get("genres")),
            keywords=_names(_keyword_items(movie.get("keywords"))),
            cover_url=cover_url,
            original_title=_text(movie.get("original_title"), _TITLE_MAX),
            original_language=_text(movie.get("original_language"), 20),
            runtime=runtime if runtime and runtime > 0 else None,
            tagline=_text(movie.get("tagline"), 500),
            vote_average=_number(movie.get("vote_average")),
            vote_count=_int(movie.get("vote_count")),
            fetched_at=self._clock(),
        )

    def _get(
        self, path: str, params: Mapping[str, object], *, allow_not_found: bool = False
    ) -> Any:
        self._throttle.wait()
        url = f"{self._base_url}{path}?{urlencode(params)}"
        try:
            data = request_json(
                self._transport,
                "GET",
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            if error.status == 404 and allow_not_found:
                return None
            raise self._map_http_error(error) from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach TMDB") from error
        except ValueError as error:
            raise SourceUnavailable("TMDB returned a response that is not JSON") from error
        if not isinstance(data, dict):
            raise SourceUnavailable("TMDB returned an unexpected response")
        return data

    @staticmethod
    def _map_http_error(error: HttpError) -> Exception:
        if error.status == 429 or error.status >= 500:
            return SourceUnavailable(f"TMDB is unavailable or rate limiting (HTTP {error.status})")
        hint = " Check TMDB_READ_ACCESS_TOKEN." if error.status in (401, 403) else ""
        return SourceRequestError(f"TMDB rejected the request (HTTP {error.status}).{hint}")
