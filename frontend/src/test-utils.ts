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

export function searchBody(query: string, results: unknown[]) {
  return { query, results };
}
