import time
from collections.abc import Callable

from catalog.http import (
    HttpError,
    NetworkError,
    RetryPolicy,
    Transport,
    request_json,
    urllib_transport_no_redirect,
)
from catalog.ratelimit import Throttle
from catalog.sources.base import SourceUnavailable
from catalog.sources.musicbrainz import normalize_mbid

BASE_URL = "https://coverartarchive.org"
SIZES = (250, 500, 1200)
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class CoverArtArchive:
    """Which release-groups have a front cover, and the stable URL to hotlink it from.

    The archive answers 307 (redirect to the image) when a front cover exists and 404 when not.
    We keep the stable URL by id, never the archive.org address it redirects to.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        throttle: Throttle,
        size: int = 500,
        transport: Transport = urllib_transport_no_redirect,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        if size not in SIZES:
            raise ValueError(f"Cover size must be one of {SIZES}")
        self._user_agent = user_agent
        self._throttle = throttle
        self._size = size
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._base_url = base_url

    def __repr__(self) -> str:
        return f"CoverArtArchive(size={self._size})"

    def front_cover_url(self, release_group_mbid: str) -> str | None:
        """The hotlink URL if the release-group has a front cover, else None."""
        mbid = normalize_mbid(release_group_mbid)
        if mbid is None:
            return None
        url = f"{self._base_url}/release-group/{mbid}/front-{self._size}"
        self._throttle.wait()
        try:
            request_json(
                self._transport,
                "HEAD",
                url,
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            if error.status in _REDIRECTS:
                return url
            if error.status == 404:
                return None
            # Not knowing is different from "no cover": stop, so the album is retried on a re-run.
            raise SourceUnavailable(
                f"Cover Art Archive is unavailable (HTTP {error.status})"
            ) from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach the Cover Art Archive") from error
        except ValueError:
            return url  # a 2xx answer to HEAD has no body to parse, which is fine
        return url
