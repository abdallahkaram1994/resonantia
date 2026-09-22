import { expect, test, vi } from "vitest";
import { getItem, getSimilarItems, search, SearchError } from "./api";
import { groupedBody, jsonResponse, rawFilm, rawItemDetail, searchBody, stubFetch } from "./test-utils";

async function failure(promise: Promise<unknown>): Promise<SearchError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(SearchError);
    return error as SearchError;
  }
  throw new Error("expected the call to fail");
}

// --- search -------------------------------------------------------------------------------

test("the query is URL-encoded, with no types or eras by default", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));

  await search("a b&c=d/é #1");

  expect(fetchMock).toHaveBeenCalledWith("/api/search/?q=a+b%26c%3Dd%2F%C3%A9+%231", {
    signal: undefined,
  });
});

test("types and eras are sent only when given", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));

  await search("x", {
    types: ["game", "album"],
    eras: [
      { start: 1980, end: 1989 },
      { start: 2000, end: 2009 },
    ],
  });

  const url = new URL(fetchMock.mock.calls[0][0], "http://localhost");
  expect(url.searchParams.get("types")).toBe("game,album");
  expect(url.searchParams.get("eras")).toBe("1980-1989,2000-2009");
});

test("an empty types or eras list is left out of the request", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));

  await search("x", { types: [], eras: [] });

  const url = new URL(fetchMock.mock.calls[0][0], "http://localhost");
  expect(url.searchParams.has("types")).toBe(false);
  expect(url.searchParams.has("eras")).toBe(false);
});

test("a single/blended response is mapped to camelCase fields", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(searchBody("rain", [rawFilm(1), rawFilm(2, { release_year: null })])),
    ),
  );

  const response = await search("rain");

  expect(response.layout).toBe("single");
  expect(response.mode).toBe("vibe");
  if (response.layout === "grouped") throw new Error("expected results, not groups");
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

test("a grouped response carries groups, not results", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        groupedBody("x", [
          { media_type: "film", results: [rawFilm(1)] },
          { media_type: "game", results: [] },
        ]),
      ),
    ),
  );

  const response = await search("x");

  expect(response.layout).toBe("grouped");
  if (response.layout !== "grouped") throw new Error("expected groups");
  expect(response.groups).toEqual([
    { mediaType: "film", results: [expect.objectContaining({ title: "Film 1" })] },
    { mediaType: "game", results: [] },
  ]);
});

test("notices come through as plain strings, junk dropped", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(searchBody("x", [], { notices: ["a notice", 5, null, "another"] })),
    ),
  );

  const response = await search("x");

  expect(response.notices).toEqual(["a notice", "another"]);
});

test.each([
  ["a film cover host", "https://image.tmdb.org/t/p/w342/a.jpg", "film", true],
  ["a game cover on the film host", "https://image.tmdb.org/t/p/w342/a.jpg", "game", false],
  ["a game cover host", "https://images.igdb.com/igdb/image/upload/t_cover_big/a.jpg", "game", true],
  [
    "an album cover host",
    "https://coverartarchive.org/release-group/1/front-500",
    "album",
    true,
  ],
  ["an album cover on the game host", "https://images.igdb.com/x.jpg", "album", false],
  ["another host entirely", "https://evil.example/poster.jpg", "film", false],
])("%s", async (_name, coverUrl, mediaType, kept) => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        searchBody("x", [{ ...rawFilm(1), media_type: mediaType, cover_url: coverUrl }]),
      ),
    ),
  );

  const response = await search("x");
  if (response.layout === "grouped") throw new Error("expected results");

  expect(response.results[0].coverUrl).toBe(kept ? coverUrl : null);
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
          { id: 5, title: "Bad type", media_type: "book" },
          rawFilm(6, { release_year: "2001" }),
        ]),
      ),
    ),
  );

  const response = await search("x");
  if (response.layout === "grouped") throw new Error("expected results");

  expect(response.results.map((r) => r.id)).toEqual([1, 6]);
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

  await expect(search("x", { signal: controller.signal })).rejects.toMatchObject({
    name: "AbortError",
  });
});

test.each([
  ["not JSON", new Response("<html>bad gateway</html>", { status: 200 })],
  ["an array", jsonResponse([])],
  ["a missing layout", jsonResponse({ query: "x", mode: "vibe", results: [] })],
  ["a bad layout", jsonResponse({ query: "x", mode: "vibe", layout: "sideways", results: [] })],
  ["a missing mode", jsonResponse({ query: "x", layout: "single", results: [] })],
  ["a missing query", jsonResponse({ layout: "single", mode: "vibe", results: [] })],
])("a 200 with %s is treated as unavailable", async (_name, response) => {
  stubFetch(() => Promise.resolve(response));

  const error = await failure(search("x"));

  expect(error.kind).toBe("unavailable");
});

test("the abort signal is passed to fetch", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(searchBody("x", []))));
  const controller = new AbortController();

  await search("x", { signal: controller.signal });

  expect(fetchMock).toHaveBeenCalledWith(expect.any(String), { signal: controller.signal });
  vi.unstubAllGlobals();
});

// --- item detail ----------------------------------------------------------------------------

test("an item detail is mapped to camelCase fields, per-type details included", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        rawItemDetail({
          media_type: "album",
          details: { artist: "Band A", tags: ["indie"], wikipedia: null },
          scores: [],
        }),
      ),
    ),
  );

  const item = await getItem(1);

  expect(item.mediaType).toBe("album");
  expect(item.details.artist).toBe("Band A");
  expect(item.details.tags).toEqual(["indie"]);
  expect(item.details.wikipedia).toBeNull();
  expect(item.scores).toEqual([]);
});

test("a wikipedia credit is parsed when complete", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        rawItemDetail({
          media_type: "album",
          details: {
            artist: "Band A",
            tags: [],
            wikipedia: { title: "Studio One", url: "https://en.wikipedia.org/wiki/Studio_One" },
          },
        }),
      ),
    ),
  );

  const item = await getItem(1);

  expect(item.details.wikipedia).toEqual({
    title: "Studio One",
    url: "https://en.wikipedia.org/wiki/Studio_One",
  });
});

test("a 404 is a not-found error", async () => {
  stubFetch(() => Promise.resolve(jsonResponse({ detail: "Not found." }, 404)));

  const error = await failure(getItem(999999));

  expect(error.kind).toBe("invalid");
  expect(error.message).toBe("That item could not be found.");
});

test("no query means no q param, and no explanation field at all", async () => {
  const fetchMock = stubFetch(() => Promise.resolve(jsonResponse(rawItemDetail())));

  const item = await getItem(1);

  expect(fetchMock).toHaveBeenCalledWith("/api/items/1/", { signal: undefined });
  expect(item.explanation).toBeNull();
});

test("a query is sent as ?q= and a string explanation is parsed", async () => {
  const fetchMock = stubFetch(() =>
    Promise.resolve(jsonResponse(rawItemDetail({ explanation: "Both are moody night drives." }))),
  );

  const item = await getItem(1, { query: "a rainy night drive" });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/items/1/?q=a+rainy+night+drive",
    expect.objectContaining({}),
  );
  expect(item.explanation).toBe("Both are moody night drives.");
});

test("a non-string explanation is dropped rather than shown", async () => {
  stubFetch(() => Promise.resolve(jsonResponse(rawItemDetail({ explanation: 5 }))));

  const item = await getItem(1, { query: "x" });

  expect(item.explanation).toBeNull();
});

test("an item detail cover is dropped when it is on the wrong host for its type", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(rawItemDetail({ media_type: "album", cover_url: "https://image.tmdb.org/x.jpg" })),
    ),
  );

  const item = await getItem(1);

  expect(item.coverUrl).toBeNull();
});

// --- more like this ---------------------------------------------------------------------------

test("similar items are grouped and mapped the same way as search results", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse({
        groups: [
          { media_type: "film", results: [rawFilm(1)] },
          { media_type: "game", results: [] },
        ],
      }),
    ),
  );

  const groups = await getSimilarItems(1);

  expect(groups).toEqual([
    { mediaType: "film", results: [expect.objectContaining({ title: "Film 1" })] },
    { mediaType: "game", results: [] },
  ]);
});

test("a 404 similar-items response is a not-found error", async () => {
  stubFetch(() => Promise.resolve(jsonResponse({ detail: "Not found." }, 404)));

  const error = await failure(getSimilarItems(999999));

  expect(error.kind).toBe("invalid");
});
