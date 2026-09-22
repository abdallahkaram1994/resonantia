export type MediaType = "film" | "game" | "album";

export type SearchResult = {
  id: number;
  mediaType: MediaType;
  title: string;
  releaseYear: number | null;
  coverUrl: string | null;
};

export type Layout = "single" | "grouped" | "blended";
export type SearchMode = "vibe" | "text";

export type ResultGroup = { mediaType: MediaType; results: SearchResult[] };

type SearchResponseCommon = { query: string; mode: SearchMode; notices: string[] };

export type SearchResponse =
  | (SearchResponseCommon & { layout: "single" | "blended"; results: SearchResult[] })
  | (SearchResponseCommon & { layout: "grouped"; groups: ResultGroup[] });

export type Era = { start: number; end: number };

export type SearchOptions = {
  types?: MediaType[];
  eras?: Era[];
  signal?: AbortSignal;
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
const NOT_FOUND = "That item could not be found.";
const MAX_DETAIL_LENGTH = 200;

// Covers are hotlinked straight from each source's own CDN, and nowhere else.
const COVER_HOSTS: Record<MediaType, string> = {
  film: "https://image.tmdb.org/",
  game: "https://images.igdb.com/",
  album: "https://coverartarchive.org/",
};

const MEDIA_TYPES: readonly MediaType[] = ["film", "game", "album"];

function isMediaType(value: unknown): value is MediaType {
  return typeof value === "string" && (MEDIA_TYPES as readonly string[]).includes(value);
}

function isLayout(value: unknown): value is Layout {
  return value === "single" || value === "grouped" || value === "blended";
}

function isSearchMode(value: unknown): value is SearchMode {
  return value === "vibe" || value === "text";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function coverUrl(value: unknown, mediaType: MediaType): string | null {
  return typeof value === "string" && value.startsWith(COVER_HOSTS[mediaType]) ? value : null;
}

function parseResult(value: unknown): SearchResult | null {
  if (!isRecord(value)) return null;
  const { id, media_type, title, release_year, cover_url } = value;
  if (typeof id !== "number" || typeof title !== "string" || !isMediaType(media_type)) {
    return null;
  }
  return {
    id,
    mediaType: media_type,
    title,
    releaseYear: typeof release_year === "number" ? release_year : null,
    coverUrl: coverUrl(cover_url, media_type),
  };
}

function parseResults(value: unknown): SearchResult[] {
  if (!Array.isArray(value)) return [];
  return value.map(parseResult).filter((r): r is SearchResult => r !== null);
}

function parseGroups(value: unknown): ResultGroup[] {
  if (!Array.isArray(value)) return [];
  const groups: ResultGroup[] = [];
  for (const entry of value) {
    if (!isRecord(entry) || !isMediaType(entry.media_type)) continue;
    groups.push({ mediaType: entry.media_type, results: parseResults(entry.results) });
  }
  return groups;
}

function parseNotices(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((n): n is string => typeof n === "string");
}

function parseResponse(data: unknown): SearchResponse {
  if (
    !isRecord(data) ||
    typeof data.query !== "string" ||
    !isLayout(data.layout) ||
    !isSearchMode(data.mode)
  ) {
    throw new SearchError("unavailable", UNAVAILABLE);
  }
  const common = { query: data.query, mode: data.mode, notices: parseNotices(data.notices) };
  if (data.layout === "grouped") {
    return { ...common, layout: data.layout, groups: parseGroups(data.groups) };
  }
  return { ...common, layout: data.layout, results: parseResults(data.results) };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function shortDetail(body: unknown): string {
  const detail = isRecord(body) && typeof body.detail === "string" ? body.detail : "";
  return detail && detail.length <= MAX_DETAIL_LENGTH ? detail : "";
}

async function get(path: string, signal?: AbortSignal): Promise<Response> {
  try {
    return await fetch(path, { signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SearchError("network", "Could not reach the server. Check your connection.");
  }
}

function eraParam(era: Era): string {
  return `${era.start}-${era.end}`;
}

export async function search(query: string, options: SearchOptions = {}): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (options.types && options.types.length > 0) {
    params.set("types", options.types.join(","));
  }
  if (options.eras && options.eras.length > 0) {
    params.set("eras", options.eras.map(eraParam).join(","));
  }

  const response = await get(`/api/search/?${params.toString()}`, options.signal);

  if (response.status === 400) {
    const body = await readJson(response);
    throw new SearchError("invalid", shortDetail(body) || "That search could not be used.");
  }
  if (!response.ok) {
    throw new SearchError("unavailable", UNAVAILABLE);
  }
  return parseResponse(await readJson(response));
}

export type ItemScore = { source: string; value: number; voteCount: number | null };

export type WikipediaCredit = { title: string; url: string };

export type ItemDetails = {
  genres: string[];
  keywords: string[];
  themes: string[];
  tagline: string;
  runtime: number | null;
  artist: string;
  tags: string[];
  wikipedia: WikipediaCredit | null;
};

export type ItemDetail = {
  id: number;
  mediaType: MediaType;
  title: string;
  releaseYear: number | null;
  coverUrl: string | null;
  summary: string;
  details: ItemDetails;
  scores: ItemScore[];
};

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function parseWikipediaCredit(value: unknown): WikipediaCredit | null {
  if (!isRecord(value) || typeof value.title !== "string" || typeof value.url !== "string") {
    return null;
  }
  return { title: value.title, url: value.url };
}

function parseDetails(value: unknown): ItemDetails {
  const details = isRecord(value) ? value : {};
  return {
    genres: stringArray(details.genres),
    keywords: stringArray(details.keywords),
    themes: stringArray(details.themes),
    tagline: typeof details.tagline === "string" ? details.tagline : "",
    runtime: typeof details.runtime === "number" ? details.runtime : null,
    artist: typeof details.artist === "string" ? details.artist : "",
    tags: stringArray(details.tags),
    wikipedia: parseWikipediaCredit(details.wikipedia),
  };
}

function parseScore(value: unknown): ItemScore | null {
  if (!isRecord(value) || typeof value.source !== "string" || typeof value.value !== "number") {
    return null;
  }
  return {
    source: value.source,
    value: value.value,
    voteCount: typeof value.vote_count === "number" ? value.vote_count : null,
  };
}

function parseItemDetail(data: unknown): ItemDetail | null {
  if (!isRecord(data) || typeof data.id !== "number" || !isMediaType(data.media_type)) {
    return null;
  }
  const { id, media_type, title, release_year, cover_url, summary, scores } = data;
  return {
    id,
    mediaType: media_type,
    title: typeof title === "string" ? title : "",
    releaseYear: typeof release_year === "number" ? release_year : null,
    coverUrl: coverUrl(cover_url, media_type),
    summary: typeof summary === "string" ? summary : "",
    details: parseDetails(data.details),
    scores: Array.isArray(scores)
      ? scores.map(parseScore).filter((s): s is ItemScore => s !== null)
      : [],
  };
}

async function getItemJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await get(path, signal);
  if (response.status === 404) {
    throw new SearchError("invalid", NOT_FOUND);
  }
  if (!response.ok) {
    throw new SearchError("unavailable", UNAVAILABLE);
  }
  return readJson(response);
}

export async function getItem(id: number, signal?: AbortSignal): Promise<ItemDetail> {
  const detail = parseItemDetail(await getItemJson(`/api/items/${id}/`, signal));
  if (detail === null) throw new SearchError("unavailable", UNAVAILABLE);
  return detail;
}

export async function getSimilarItems(id: number, signal?: AbortSignal): Promise<ResultGroup[]> {
  const body = await getItemJson(`/api/items/${id}/similar/`, signal);
  return isRecord(body) ? parseGroups(body.groups) : [];
}
