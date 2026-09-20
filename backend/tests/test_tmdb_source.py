"""TMDB adapter tests. Fixtures are invented films in TMDB's response shape (see
tests/fixtures/tmdb/README.md); no real TMDB content is stored in the repo."""

import json
from datetime import UTC, datetime

import pytest

from catalog.http import HttpResponse, NetworkError, RetryPolicy
from catalog.sources.base import SourceRequestError, SourceUnavailable
from catalog.sources.tmdb import TmdbFilmSource, _year
from tests.helpers import CountingThrottle, FakeClock, RoutingTransport, fixture_bytes

TOKEN = "tmdb-token-not-real"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
IMAGE_BASE = "https://image.tmdb.org/t/p/w342"


def fixture(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, fixture_bytes(f"tmdb/{name}.json"))


def inline(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload).encode())


def default_handler(path: str, query: dict[str, str]) -> HttpResponse:
    if path.endswith("/discover/movie"):
        if query["sort_by"] == "popularity.desc":
            return fixture("discover_mid_page1")
        return fixture(f"discover_popular_page{query['page']}")
    movie_id = path.rsplit("/", 1)[1]
    return fixture(f"movie_{movie_id}")


def make_source(handler=default_handler, **overrides: object):
    transport = RoutingTransport(handler)
    throttle = CountingThrottle()
    clock = FakeClock()
    kwargs: dict[str, object] = {
        "token": TOKEN,
        "throttle": throttle,
        "image_base_url": IMAGE_BASE + "/",
        "min_vote_count": 1000,
        "mid_tail_min_vote_count": 200,
        "transport": transport,
        "sleep": clock.sleep,
        "clock": lambda: NOW,
    }
    kwargs.update(overrides)
    return TmdbFilmSource(**kwargs), transport, throttle  # type: ignore[arg-type]


def test_popular_films_walk_the_pages_and_skip_duplicates() -> None:
    source, _, _ = make_source()

    ids = [film.source_id for film in source.popular_films()]

    assert ids == [1001, 1002, 1003, 1004]


def test_a_full_film_is_parsed() -> None:
    source, _, _ = make_source()

    film = next(source.popular_films())

    assert film.source_id == 1001
    assert film.title == "Neon Rain Drive"
    assert film.release_year == 2017
    assert film.overview.startswith("A night courier")
    assert film.genres == ("Science Fiction", "Thriller")
    assert film.keywords == ("rain", "night")
    assert film.cover_url == "https://image.tmdb.org/t/p/w342/neonRainDrive01.jpg"
    assert film.runtime == 118
    assert film.tagline == "Every light lies."
    assert film.vote_average == 7.6
    assert film.vote_count == 4200
    assert film.fetched_at == NOW
    assert film.is_embeddable is True


def test_edge_films_are_parsed_without_crashing() -> None:
    source, _, _ = make_source()

    films = {film.source_id: film for film in source.popular_films()}

    no_date = films[1002]
    assert no_date.release_year is None
    assert no_date.runtime is None
    assert no_date.genres == () and no_date.keywords == ()
    assert no_date.is_embeddable is False

    no_overview = films[1003]
    assert no_overview.overview == ""
    assert no_overview.cover_url == ""
    assert no_overview.is_embeddable is False

    tolerant_keywords = films[1004]
    assert tolerant_keywords.keywords == ("desert",)
    assert tolerant_keywords.cover_url == ""
    assert tolerant_keywords.is_embeddable is True


def test_discover_requests_use_the_popularity_threshold() -> None:
    source, transport, _ = make_source()

    next(source.popular_films())

    first = transport.calls[0]
    assert first["path"].endswith("/discover/movie")
    assert first["query"] == {
        "sort_by": "vote_count.desc",
        "vote_count.gte": "1000",
        "include_adult": "false",
        "language": "en-US",
        "page": "1",
    }


def test_mid_tail_requests_use_the_band_below_the_threshold() -> None:
    source, transport, _ = make_source()

    films = list(source.mid_tail_films())

    assert [film.source_id for film in films] == [1005]
    query = transport.calls[0]["query"]
    assert query["sort_by"] == "popularity.desc"
    assert query["vote_count.gte"] == "200"
    assert query["vote_count.lte"] == "999"


def test_details_request_asks_for_keywords() -> None:
    source, transport, _ = make_source()

    next(source.popular_films())

    detail = transport.calls[1]
    assert detail["path"].endswith("/movie/1001")
    assert detail["query"] == {"append_to_response": "keywords", "language": "en-US"}


def test_token_is_sent_as_a_bearer_header_and_never_in_the_url() -> None:
    source, transport, _ = make_source()

    list(source.mid_tail_films())

    for call in transport.calls:
        assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in call["url"]
    assert TOKEN not in repr(source)


def test_films_are_fetched_lazily() -> None:
    source, transport, _ = make_source()

    next(source.popular_films())

    assert len(transport.calls) == 2  # one discover page and one film, nothing more


def test_stops_at_the_last_page() -> None:
    source, transport, _ = make_source()

    list(source.popular_films())

    pages = [c["query"]["page"] for c in transport.calls if c["path"].endswith("/discover/movie")]
    assert pages == ["1", "2"]


def test_every_request_is_throttled() -> None:
    source, transport, throttle = make_source()

    list(source.mid_tail_films())

    assert throttle.waits == len(transport.calls) == 2


def test_a_missing_film_is_skipped_and_the_walk_continues() -> None:
    def handler(path: str, query: dict[str, str]) -> HttpResponse:
        if path.endswith("/movie/1002"):
            return fixture("error_404", 404)
        return default_handler(path, query)

    source, _, _ = make_source(handler)

    ids = [film.source_id for film in source.popular_films()]

    assert ids == [1001, 1003, 1004]


def test_hostile_field_values_are_neutralised() -> None:
    hostile = {
        "id": 1001,
        "title": "T" * 1000,
        "overview": 123,
        "release_date": ["2017-05-19"],
        "poster_path": {"x": 1},
        "vote_average": "9.9",
        "vote_count": True,
        "runtime": "long",
        "genres": "Drama",
        "keywords": "rain",
    }

    def handler(path: str, query: dict[str, str]) -> HttpResponse:
        if path.endswith("/discover/movie"):
            return inline({"results": [{"id": 1001}], "total_pages": 1})
        return inline(hostile)

    source, _, _ = make_source(handler)

    film = next(source.popular_films())

    assert len(film.title) == 500
    assert film.overview == ""
    assert film.release_year is None
    assert film.cover_url == ""
    assert film.vote_average is None
    assert film.vote_count is None
    assert film.runtime is None
    assert film.genres == () and film.keywords == ()


def test_a_film_without_a_title_or_id_is_dropped() -> None:
    def handler(path: str, query: dict[str, str]) -> HttpResponse:
        if path.endswith("/discover/movie"):
            return inline(
                {"results": [{"id": 1}, {"id": 2}, {"id": "3"}, "junk"], "total_pages": 1}
            )
        if path.endswith("/movie/1"):
            return inline({"id": 1, "title": "   "})
        if path.endswith("/movie/2"):
            return inline({"title": "No id"})
        return inline({})

    source, _, _ = make_source(handler)

    assert list(source.popular_films()) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2017-05-19", 2017),
        ("1888-01-01", 1888),
        ("", None),
        ("abcd-ef-gh", None),
        ("2017", None),
        ("0001-01-01", None),
        ("9999-01-01", None),
        (None, None),
        (20170519, None),
    ],
)
def test_year_parsing(value: object, expected: int | None) -> None:
    assert _year(value) == expected


def test_bad_token_is_a_request_error_that_does_not_leak_it() -> None:
    def handler(path: str, query: dict[str, str]) -> HttpResponse:
        return fixture("error_401", 401)

    source, transport, _ = make_source(handler)

    with pytest.raises(SourceRequestError) as excinfo:
        next(source.popular_films())

    assert "HTTP 401" in str(excinfo.value)
    assert "TMDB_READ_ACCESS_TOKEN" in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)
    assert len(transport.calls) == 1


def test_rate_limiting_that_never_clears_is_unavailable() -> None:
    def handler(path: str, query: dict[str, str]) -> HttpResponse:
        return HttpResponse(429, {}, b'{"status_code": 25}')

    source, transport, _ = make_source(handler, retry=RetryPolicy(max_retries=2))

    with pytest.raises(SourceUnavailable):
        next(source.popular_films())

    assert len(transport.calls) == 3


def test_server_errors_are_unavailable() -> None:
    source, _, _ = make_source(lambda path, query: HttpResponse(503, {}, b"{}"))

    with pytest.raises(SourceUnavailable):
        next(source.popular_films())


def test_network_errors_are_unavailable() -> None:
    source, _, _ = make_source(lambda path, query: NetworkError("URLError"))

    with pytest.raises(SourceUnavailable):
        next(source.popular_films())


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(200, {}, b"<html>oops</html>"),
        inline([]),
        inline({"page": 1}),
        inline({"results": "nope", "total_pages": 1}),
    ],
)
def test_unusable_discover_responses_are_unavailable(response: HttpResponse) -> None:
    source, _, _ = make_source(lambda path, query: response)

    with pytest.raises(SourceUnavailable):
        next(source.popular_films())
