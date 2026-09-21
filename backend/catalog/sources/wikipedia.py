import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

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

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_PAGE = "https://en.wikipedia.org/wiki/"
ENTITY_BATCH = 50  # wbgetentities accepts up to 50 ids
EXTRACT_BATCH = 20  # prop=extracts returns at most 20 intros per request
MAX_CHARS = 4000
_QID = re.compile(r"Q[1-9][0-9]{0,12}")
_MAX_REDIRECT_HOPS = 5


@dataclass(frozen=True)
class WikiIntro:
    wikidata_id: str
    title: str
    text: str
    url: str


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class WikipediaClient:
    """English Wikipedia intros for albums, found through their Wikidata ids.

    Both steps are batched (50 ids and 20 titles per request) so a few thousand albums need only
    a few hundred requests. Text is CC BY-SA: show "Source: Wikipedia" and the licence with it.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        throttle: Throttle,
        transport: Transport = urllib_transport,
        retry: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        wikidata_api: str = WIKIDATA_API,
        wikipedia_api: str = WIKIPEDIA_API,
    ) -> None:
        self._user_agent = user_agent
        self._throttle = throttle
        self._transport = transport
        self._retry = retry
        self._timeout = timeout
        self._sleep = sleep
        self._wikidata_api = wikidata_api
        self._wikipedia_api = wikipedia_api

    def __repr__(self) -> str:
        return "WikipediaClient()"

    def intros(self, wikidata_ids: Iterable[str]) -> dict[str, WikiIntro]:
        """Intro text for each Wikidata id that has an English article with text. Others are
        left out: a missing summary is normal and never an error."""
        ids = list(dict.fromkeys(i for i in wikidata_ids if _QID.fullmatch(i)))
        titles = self._titles(ids)
        pages = self._extracts(list(dict.fromkeys(titles.values())))
        found: dict[str, WikiIntro] = {}
        for qid, title in titles.items():
            page = pages.get(title)
            if page is not None:
                page_title, text = page
                found[qid] = WikiIntro(
                    wikidata_id=qid,
                    title=page_title,
                    text=text,
                    url=WIKIPEDIA_PAGE + quote(page_title.replace(" ", "_"), safe="_(),'!*-.~"),
                )
        return found

    def _titles(self, ids: Sequence[str]) -> dict[str, str]:
        titles: dict[str, str] = {}
        for batch in _chunks(ids, ENTITY_BATCH):
            data = self._get(
                self._wikidata_api,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "sitelinks",
                    "sitefilter": "enwiki",
                    "format": "json",
                    "formatversion": "2",
                },
            )
            entities = data.get("entities")
            if not isinstance(entities, dict):
                raise SourceUnavailable("Wikidata returned an unexpected response")
            for qid, entity in entities.items():
                sitelinks = entity.get("sitelinks") if isinstance(entity, dict) else None
                link = sitelinks.get("enwiki") if isinstance(sitelinks, dict) else None
                title = link.get("title") if isinstance(link, dict) else None
                if qid in batch and isinstance(title, str) and title.strip():
                    titles[qid] = title.strip()
        return titles

    def _extracts(self, titles: Sequence[str]) -> dict[str, tuple[str, str]]:
        """Map each requested title to (final page title, intro text), following normalization
        and redirects."""
        result: dict[str, tuple[str, str]] = {}
        for batch in _chunks(titles, EXTRACT_BATCH):
            data = self._get(
                self._wikipedia_api,
                {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "exlimit": "max",
                    "redirects": "1",
                    "titles": "|".join(batch),
                    "format": "json",
                    "formatversion": "2",
                },
            )
            query = data.get("query")
            if not isinstance(query, dict) or not isinstance(query.get("pages"), list):
                raise SourceUnavailable("Wikipedia returned an unexpected response")
            texts: dict[str, str] = {}
            for page in query["pages"]:
                if not isinstance(page, dict) or page.get("missing"):
                    continue
                title, extract = page.get("title"), page.get("extract")
                if isinstance(title, str) and isinstance(extract, str) and extract.strip():
                    texts[title] = " ".join(extract.split())[:MAX_CHARS]
            aliases = {
                **self._mapping(query.get("normalized")),
                **self._mapping(query.get("redirects")),
            }
            for requested in batch:
                final = requested
                for _ in range(_MAX_REDIRECT_HOPS):
                    if final not in aliases:
                        break
                    final = aliases[final]
                if final in texts:
                    result[requested] = (final, texts[final])
        return result

    @staticmethod
    def _mapping(entries: object) -> dict[str, str]:
        if not isinstance(entries, list):
            return {}
        return {
            e["from"]: e["to"]
            for e in entries
            if isinstance(e, dict)
            and isinstance(e.get("from"), str)
            and isinstance(e.get("to"), str)
        }

    def _get(self, endpoint: str, params: Mapping[str, str]) -> dict[str, Any]:
        self._throttle.wait()
        try:
            data = request_json(
                self._transport,
                "GET",
                f"{endpoint}?{urlencode(params)}",
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
                retry=self._retry,
                sleep=self._sleep,
            )
        except HttpError as error:
            if error.status == 429 or error.status >= 500:
                raise SourceUnavailable(
                    f"Wikimedia is unavailable or rate limiting (HTTP {error.status})"
                ) from error
            raise SourceRequestError(
                f"Wikimedia rejected the request (HTTP {error.status})"
            ) from error
        except NetworkError as error:
            raise SourceUnavailable("Could not reach Wikimedia") from error
        except ValueError as error:
            raise SourceUnavailable("Wikimedia returned a response that is not JSON") from error
        if not isinstance(data, dict) or "error" in data:
            raise SourceUnavailable("Wikimedia returned an unexpected response")
        return data
