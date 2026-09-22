import { vi } from "vitest";

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function stubFetch(handler: (url: string) => Promise<Response>) {
  const fetchMock = vi.fn((url: string) => handler(url));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// A result exactly as the backend sends it.
export function rawFilm(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    media_type: "film",
    title: `Film ${id}`,
    release_year: 2000 + id,
    cover_url: `https://image.tmdb.org/t/p/w342/film${id}.jpg`,
    score: 0.6,
    ...overrides,
  };
}

export function rawGame(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    media_type: "game",
    title: `Game ${id}`,
    release_year: 2000 + id,
    cover_url: `https://images.igdb.com/igdb/image/upload/t_cover_big/co${id}.jpg`,
    score: 0.6,
    ...overrides,
  };
}

export function rawAlbum(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    media_type: "album",
    title: `Album ${id}`,
    release_year: 2000 + id,
    cover_url: `https://coverartarchive.org/release-group/${id}/front-500`,
    score: 0.6,
    ...overrides,
  };
}

// A single search response exactly as the backend sends it.
export function searchBody(
  query: string,
  results: unknown[],
  overrides: Record<string, unknown> = {},
) {
  return { query, layout: "single", mode: "vibe", notices: [], results, ...overrides };
}

// A blended search response (the shape a default, all-types search gets back).
export function blendedBody(
  query: string,
  results: unknown[],
  overrides: Record<string, unknown> = {},
) {
  return { query, layout: "blended", mode: "vibe", notices: [], results, ...overrides };
}

// A grouped search response.
export function groupedBody(
  query: string,
  groups: { media_type: string; results: unknown[] }[],
  overrides: Record<string, unknown> = {},
) {
  return { query, layout: "grouped", mode: "vibe", notices: [], groups, ...overrides };
}

// An item detail record exactly as the backend sends it.
export function rawItemDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    media_type: "film",
    title: "The Film",
    release_year: 2001,
    cover_url: "https://image.tmdb.org/t/p/w342/film1.jpg",
    summary: "A summary.",
    details: { genres: ["Drama"], keywords: ["rain"], tagline: "", runtime: 100 },
    scores: [{ source: "tmdb", value: 7.4, vote_count: 1500 }],
    ...overrides,
  };
}
