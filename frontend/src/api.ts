export type SearchResult = {
  id: number;
  mediaType: string;
  title: string;
  releaseYear: number | null;
  coverUrl: string | null;
};

export type SearchResponse = {
  query: string;
  results: SearchResult[];
};

export type SearchErrorKind = "invalid" | "unavailable" | "network";

export class SearchError extends Error {
  readonly kind: SearchErrorKind;

  constructor(kind: SearchErrorKind, message: string) {
    super(message);
    this.name = "SearchError";
    this.kind = kind;
  }
}

const UNAVAILABLE = "Search is temporarily unavailable. Please try again in a little while.";
// Covers are hotlinked from TMDB's image CDN and nowhere else.
const COVER_PREFIX = "https://image.tmdb.org/";
const MAX_DETAIL_LENGTH = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseResult(value: unknown): SearchResult | null {
  if (!isRecord(value)) return null;
  const { id, media_type, title, release_year, cover_url } = value;
  if (typeof id !== "number" || typeof title !== "string" || typeof media_type !== "string") {
    return null;
  }
  return {
    id,
    mediaType: media_type,
    title,
    releaseYear: typeof release_year === "number" ? release_year : null,
    coverUrl:
      typeof cover_url === "string" && cover_url.startsWith(COVER_PREFIX) ? cover_url : null,
  };
}

function parseResponse(data: unknown): SearchResponse {
  if (!isRecord(data) || typeof data.query !== "string" || !Array.isArray(data.results)) {
    throw new SearchError("unavailable", UNAVAILABLE);
  }
  const results = data.results.map(parseResult).filter((r): r is SearchResult => r !== null);
  return { query: data.query, results };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function search(query: string, signal?: AbortSignal): Promise<SearchResponse> {
  let response: Response;
  try {
    response = await fetch(`/api/search/?q=${encodeURIComponent(query)}`, { signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SearchError("network", "Could not reach the server. Check your connection.");
  }

  if (response.status === 400) {
    const body = await readJson(response);
    const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : "";
    throw new SearchError(
      "invalid",
      detail && detail.length <= MAX_DETAIL_LENGTH ? detail : "That search could not be used.",
    );
  }
  if (!response.ok) {
    throw new SearchError("unavailable", UNAVAILABLE);
  }
  return parseResponse(await readJson(response));
}
