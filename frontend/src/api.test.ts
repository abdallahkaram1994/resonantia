import { expect, test, vi } from "vitest";
import { search, SearchError } from "./api";
import { jsonResponse, rawFilm, searchBody, stubFetch } from "./test-utils";

async function failure(promise: Promise<unknown>): Promise<SearchError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(SearchError);
    return error as SearchError;
  }
  throw new Error("expected the search to fail");
}

test("the query is URL-encoded", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));

  await search("a b&c=d/é #1");

  expect(fetchMock).toHaveBeenCalledWith("/api/search/?q=a%20b%26c%3Dd%2F%C3%A9%20%231&types=film", {
    signal: undefined,
  });
});

test("results are mapped to camelCase fields", async () => {
  stubFetch(() =>
    Promise.resolve(jsonResponse(searchBody("rain", [rawFilm(1), rawFilm(2, { release_year: null })]))),
  );

  const response = await search("rain");

  expect(response.query).toBe("rain");
  expect(response.results).toEqual([
    {
      id: 1,
      mediaType: "film",
      title: "Film 1",
      releaseYear: 2001,
      coverUrl: "https://image.tmdb.org/t/p/w342/film1.jpg",
    },
    {
      id: 2,
      mediaType: "film",
      title: "Film 2",
      releaseYear: null,
      coverUrl: "https://image.tmdb.org/t/p/w342/film2.jpg",
    },
  ]);
});

test.each([
  ["another host", "https://evil.example/poster.jpg"],
  ["a javascript URL", "javascript:alert(1)"],
  ["a data URL", "data:image/svg+xml;base64,PHN2Zz4="],
  ["plain http", "http://image.tmdb.org/t/p/w342/a.jpg"],
  ["a lookalike host", "https://image.tmdb.org.evil.example/a.jpg"],
  ["an empty string", ""],
  ["a non-string", 42],
])("a cover on %s is dropped", async (_name, coverUrl) => {
  stubFetch(() =>
    Promise.resolve(jsonResponse(searchBody("x", [rawFilm(1, { cover_url: coverUrl })]))),
  );

  const response = await search("x");

  expect(response.results[0].coverUrl).toBeNull();
});

test("results with the wrong shape are dropped and the rest kept", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        searchBody("x", [
          rawFilm(1),
          null,
          "junk",
          { id: "2", title: "String id", media_type: "film" },
          { id: 3, title: 99, media_type: "film" },
          { id: 4, title: "No type" },
          rawFilm(5, { release_year: "2001" }),
        ]),
      ),
    ),
  );

  const response = await search("x");

  expect(response.results.map((r) => r.id)).toEqual([1, 5]);
  expect(response.results[1].releaseYear).toBeNull();
});

test("a 400 shows the server's short message", async () => {
  stubFetch(() =>
    Promise.resolve(jsonResponse({ detail: "Query is too long (maximum 200 characters)." }, 400)),
  );

  const error = await failure(search("x"));

  expect(error.kind).toBe("invalid");
  expect(error.message).toBe("Query is too long (maximum 200 characters).");
});

test.each([
  ["no body", new Response("nope", { status: 400 })],
  ["a non-string detail", jsonResponse({ detail: { a: 1 } }, 400)],
  ["an over-long detail", jsonResponse({ detail: "x".repeat(500) }, 400)],
])("a 400 with %s gets a generic message", async (_name, response) => {
  stubFetch(() => Promise.resolve(response));

  const error = await failure(search("x"));

  expect(error.kind).toBe("invalid");
  expect(error.message).toBe("That search could not be used.");
});

test.each([503, 500, 502, 429])("a %i means search is unavailable", async (status) => {
  stubFetch(() => Promise.resolve(jsonResponse({ detail: "internal detail" }, status)));

  const error = await failure(search("x"));

  expect(error.kind).toBe("unavailable");
  expect(error.message).not.toContain("internal detail");
});

test("a network failure is reported as such", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

  const error = await failure(search("x"));

  expect(error.kind).toBe("network");
});

test("an aborted request rethrows the abort instead of a SearchError", async () => {
  const controller = new AbortController();
  stubFetch(() => {
    controller.abort();
    return Promise.reject(new DOMException("aborted", "AbortError"));
  });

  await expect(search("x", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
});

test.each([
  ["not JSON", new Response("<html>bad gateway</html>", { status: 200 })],
  ["an array", jsonResponse([])],
  ["a missing results list", jsonResponse({ query: "x" })],
  ["a non-list results field", jsonResponse({ query: "x", results: "nope" })],
  ["a missing query", jsonResponse({ results: [] })],
])("a 200 with %s is treated as unavailable", async (_name, response) => {
  stubFetch(() => Promise.resolve(response));

  const error = await failure(search("x"));

  expect(error.kind).toBe("unavailable");
});

test("the abort signal is passed to fetch", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));
  const controller = new AbortController();

  await search("x", controller.signal);

  expect(fetchMock).toHaveBeenCalledWith(expect.any(String), { signal: controller.signal });
  vi.unstubAllGlobals();
});
