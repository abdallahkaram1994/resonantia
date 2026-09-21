"""Wikidata and Wikipedia client tests, with invented articles in the verified response shapes
(see tests/fixtures/wikimedia/README.md)."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceRequestError, SourceUnavailable
from catalog.sources.wikipedia import MAX_CHARS, WikipediaClient
from tests.helpers import CountingThrottle, FakeClock, ScriptedTransport, fixture_bytes

AGENT = "Resonantia/0.1 (test@example.com)"


def fixture(name: str) -> HttpResponse:
    return HttpResponse(200, {}, fixture_bytes(f"wikimedia/{name}.json"))


def inline(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload).encode())


def default_handler(method: str, url: str, headers: dict[str, str], body: str):
    return fixture("wikidata_entities") if "wikidata.org" in url else fixture("wikipedia_pages")


def make_client(handler=default_handler, **overrides: object):
    transport = ScriptedTransport(handler)
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "user_agent": AGENT,
        "throttle": throttle,
        "transport": transport,
        "sleep": clock.sleep,
    }
    kwargs.update(overrides)
    return WikipediaClient(**kwargs), transport, throttle  # type: ignore[arg-type]


def query_of(call: dict) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(call["url"]).query).items()}


def wikidata_calls(transport: ScriptedTransport) -> list[dict]:
    return [c for c in transport.calls if "wikidata.org" in c["url"]]


def wikipedia_calls(transport: ScriptedTransport) -> list[dict]:
    return [c for c in transport.calls if "wikipedia.org" in c["url"]]


def test_intros_are_found_through_wikidata_including_redirects_and_normalization() -> None:
    client, _, _ = make_client()

    found = client.intros(["Q900001", "Q900002", "Q900003"])

    assert sorted(found) == ["Q900001", "Q900003"]  # Q900002 has no English article
    rainy = found["Q900001"]
    assert rainy.title == "The Rainy Hour"
    assert rainy.text == (
        "The Rainy Hour is the third studio album by the fictional band Fixture Band. "
        "It was released in 1997."
    )
    assert rainy.url == "https://en.wikipedia.org/wiki/The_Rainy_Hour"
    redirected = found["Q900003"]  # "old name" -> "Old name" -> "The Modern Title"
    assert redirected.title == "The Modern Title"
    assert redirected.text.startswith("The Modern Title is an invented article")


def test_requests_carry_a_descriptive_user_agent_and_the_expected_parameters() -> None:
    client, transport, _ = make_client()

    client.intros(["Q900001"])

    assert all(
        c["headers"]["User-Agent"] == AGENT and c["method"] == "GET" for c in transport.calls
    )
    entities = query_of(wikidata_calls(transport)[0])
    assert entities["action"] == "wbgetentities"
    assert entities["ids"] == "Q900001"
    assert entities["props"] == "sitelinks" and entities["sitefilter"] == "enwiki"
    assert entities["formatversion"] == "2"
    extracts = query_of(wikipedia_calls(transport)[0])
    assert extracts["prop"] == "extracts"
    assert extracts["exintro"] == "1" and extracts["explaintext"] == "1"
    assert extracts["redirects"] == "1"
    assert extracts["titles"] == "The Rainy Hour"


def test_ids_and_titles_are_sent_in_batches() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        params = query_of({"url": url})
        if "wikidata.org" in url:
            ids = params["ids"].split("|")
            entities = {q: {"sitelinks": {"enwiki": {"title": f"Album {q}"}}} for q in ids}
            return inline({"entities": entities})
        titles = params["titles"].split("|")
        pages = [{"title": t, "extract": f"About {t}."} for t in titles]
        return inline({"query": {"pages": pages}})

    client, transport, throttle = make_client(handler)
    ids = [f"Q{n}" for n in range(1, 121)]

    found = client.intros(ids)

    assert len(found) == 120
    assert [len(query_of(c)["ids"].split("|")) for c in wikidata_calls(transport)] == [50, 50, 20]
    assert [len(query_of(c)["titles"].split("|")) for c in wikipedia_calls(transport)] == [
        20,
        20,
        20,
        20,
        20,
        20,
    ]
    assert throttle.waits == len(transport.calls) == 9


def test_invalid_and_duplicate_ids_are_dropped_before_any_request() -> None:
    client, transport, _ = make_client()

    client.intros(["Q900001", "Q900001", "q900001", "Q0", "Qabc", "P31", "Q1|Q2", "", "Q900001\n"])

    assert query_of(wikidata_calls(transport)[0])["ids"] == "Q900001"


def test_no_valid_ids_means_no_requests() -> None:
    client, transport, _ = make_client()

    assert client.intros([]) == {}
    assert client.intros(["nope", "Q0"]) == {}
    assert transport.calls == []


def test_an_id_with_no_english_article_makes_no_extract_request() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        return inline({"entities": {"Q5": {"sitelinks": {}}}})

    client, transport, _ = make_client(handler)

    assert client.intros(["Q5"]) == {}
    assert wikipedia_calls(transport) == []


def test_missing_pages_and_empty_extracts_are_left_out() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if "wikidata.org" in url:
            links = {
                q: {"sitelinks": {"enwiki": {"title": t}}}
                for q, t in {"Q1": "Gone", "Q2": "Blank", "Q3": "Fine"}.items()
            }
            return inline({"entities": links})
        return inline(
            {
                "query": {
                    "pages": [
                        {"title": "Gone", "missing": True},
                        {"title": "Blank", "extract": "   "},
                        {"title": "Fine", "extract": "A fine article."},
                    ]
                }
            }
        )

    client, _, _ = make_client(handler)

    assert list(client.intros(["Q1", "Q2", "Q3"])) == ["Q3"]


def test_text_is_cleaned_and_capped() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if "wikidata.org" in url:
            return inline({"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "Long"}}}}})
        text = "Word  \n\n" * 5000
        return inline({"query": {"pages": [{"title": "Long", "extract": text}]}})

    client, _, _ = make_client(handler)

    text = client.intros(["Q1"])["Q1"].text

    assert len(text) == MAX_CHARS
    assert "\n" not in text and "  " not in text


@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("OK Computer", "https://en.wikipedia.org/wiki/OK_Computer"),
        ("Kid A (album)", "https://en.wikipedia.org/wiki/Kid_A_(album)"),
        ("Café del Mar", "https://en.wikipedia.org/wiki/Caf%C3%A9_del_Mar"),
        ("Who's Next", "https://en.wikipedia.org/wiki/Who's_Next"),
        ("AC/DC: Live", "https://en.wikipedia.org/wiki/AC%2FDC%3A_Live"),
        ("A?b#c", "https://en.wikipedia.org/wiki/A%3Fb%23c"),
    ],
)
def test_page_urls_are_built_safely(title: str, url: str) -> None:
    def handler(method: str, url_: str, headers: dict[str, str], body: str) -> HttpResponse:
        if "wikidata.org" in url_:
            return inline({"entities": {"Q1": {"sitelinks": {"enwiki": {"title": title}}}}})
        return inline({"query": {"pages": [{"title": title, "extract": "Text."}]}})

    client, _, _ = make_client(handler)

    assert client.intros(["Q1"])["Q1"].url == url


def test_a_redirect_loop_does_not_hang() -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if "wikidata.org" in url:
            return inline({"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "A"}}}}})
        return inline(
            {
                "query": {
                    "redirects": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                    "pages": [{"title": "Other", "extract": "x"}],
                }
            }
        )

    client, _, _ = make_client(handler)

    assert client.intros(["Q1"]) == {}


@pytest.mark.parametrize(
    "entities",
    [
        {"Q1": None},
        {"Q1": "x"},
        {"Q1": {"sitelinks": "x"}},
        {"Q1": {"sitelinks": {"enwiki": 3}}},
        {"Q1": {"sitelinks": {"enwiki": {"title": 7}}}},
        {"Q9": {"sitelinks": {"enwiki": {"title": "X"}}}},
    ],
)
def test_odd_entities_are_skipped_not_fatal(entities: object) -> None:
    client, _, _ = make_client(lambda m, u, h, b: inline({"entities": entities}))

    assert client.intros(["Q1"]) == {}


@pytest.mark.parametrize(
    "response",
    [
        inline({"entities": "nope"}),
        inline({"no_entities": 1}),
        inline({"error": {"code": "badid", "info": "x"}}),
        inline([]),
        HttpResponse(200, {}, b"<html>oops</html>"),
    ],
)
def test_an_unusable_wikidata_response_is_unavailable(response: HttpResponse) -> None:
    client, _, _ = make_client(lambda m, u, h, b: response)

    with pytest.raises(SourceUnavailable):
        client.intros(["Q1"])


@pytest.mark.parametrize(
    "extract_response",
    [inline({"query": "x"}), inline({"query": {"pages": "x"}}), inline({"batchcomplete": True})],
)
def test_an_unusable_wikipedia_response_is_unavailable(extract_response: HttpResponse) -> None:
    def handler(method: str, url: str, headers: dict[str, str], body: str) -> HttpResponse:
        if "wikidata.org" in url:
            return inline({"entities": {"Q1": {"sitelinks": {"enwiki": {"title": "A"}}}}})
        return extract_response

    client, _, _ = make_client(handler)

    with pytest.raises(SourceUnavailable):
        client.intros(["Q1"])


def test_rate_limiting_that_never_clears_is_unavailable() -> None:
    client, transport, _ = make_client(
        lambda m, u, h, b: HttpResponse(429, {}, b"{}"), retry=RetryPolicy(max_retries=2)
    )

    with pytest.raises(SourceUnavailable):
        client.intros(["Q1"])

    assert len(transport.calls) == 3


def test_a_rejected_request_is_a_request_error() -> None:
    client, _, _ = make_client(lambda m, u, h, b: HttpResponse(403, {}, b"blocked"))

    with pytest.raises(SourceRequestError, match="HTTP 403"):
        client.intros(["Q1"])


def test_a_network_failure_is_unavailable() -> None:
    client, _, _ = make_client(
        lambda m, u, h, b: NetworkError("URLError"), retry=RetryPolicy(max_retries=0)
    )

    with pytest.raises(SourceUnavailable):
        client.intros(["Q1"])
