import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { search, SearchError } from "./api";
import type { Era, MediaType, SearchResponse } from "./api";
import ResultsList from "./ResultsList";
import SearchFilters, { ALL_TYPES } from "./SearchFilters";

const MAX_QUERY_LENGTH = 200;

type SearchRequest = { query: string; types: MediaType[]; eras: Era[]; id: number };
type Outcome =
  | { requestId: number; kind: "response"; response: SearchResponse }
  | { requestId: number; kind: "error"; message: string };

function parseTypes(raw: string | null): MediaType[] {
  if (!raw) return ALL_TYPES;
  const chosen = raw
    .split(",")
    .map((t) => t.trim().toLowerCase())
    .filter((t): t is MediaType => (ALL_TYPES as string[]).includes(t));
  return chosen.length > 0 ? ALL_TYPES.filter((t) => chosen.includes(t)) : ALL_TYPES;
}

function parseEras(raw: string | null): Era[] {
  if (!raw) return [];
  const eras: Era[] = [];
  for (const part of raw.split(",")) {
    const match = /^(\d{4})-(\d{4})$/.exec(part.trim());
    if (match) eras.push({ start: Number(match[1]), end: Number(match[2]) });
  }
  return eras;
}

function fromUrl(): { query: string; types: MediaType[]; eras: Era[] } {
  const params = new URLSearchParams(window.location.search);
  return {
    query: (params.get("q") ?? "").trim(),
    types: parseTypes(params.get("types")),
    eras: parseEras(params.get("eras")),
  };
}

// Every type enabled is the default, so it is left out of the URL entirely for a clean address.
function urlFor(query: string, types: MediaType[], eras: Era[]): string {
  if (!query) return "/";
  const params = new URLSearchParams({ q: query });
  if (types.length < ALL_TYPES.length) params.set("types", types.join(","));
  if (eras.length > 0) params.set("eras", eras.map((e) => `${e.start}-${e.end}`).join(","));
  return `/search?${params.toString()}`;
}

export default function SearchPage() {
  const [input, setInput] = useState(() => fromUrl().query);
  const [types, setTypes] = useState<MediaType[]>(() => fromUrl().types);
  const [eras, setEras] = useState<Era[]>(() => fromUrl().eras);
  const [request, setRequest] = useState<SearchRequest>(() => ({ ...fromUrl(), id: 0 }));
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (!request.query) return;
    const controller = new AbortController();
    search(request.query, {
      // Every type enabled is the backend's own default too, so leaving it out keeps both the
      // request and the URL clean.
      types: request.types.length < ALL_TYPES.length ? request.types : undefined,
      eras: request.eras,
      signal: controller.signal,
    }).then(
      (response) => {
        // A newer search has replaced this one, so its late answer must not overwrite the page.
        if (controller.signal.aborted) return;
        setOutcome({ requestId: request.id, kind: "response", response });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setOutcome({
          requestId: request.id,
          kind: "error",
          message:
            error instanceof SearchError ? error.message : "Something went wrong. Please try again.",
        });
      },
    );
    return () => controller.abort();
  }, [request]);

  useEffect(() => {
    const onPopState = () => {
      const next = fromUrl();
      setInput(next.query);
      setTypes(next.types);
      setEras(next.eras);
      setRequest((current) => ({ ...next, id: current.id + 1 }));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();
    if (!query) return;
    window.history.pushState(null, "", urlFor(query, types, eras));
    setRequest((current) => ({ query, types, eras, id: current.id + 1 }));
  }

  // A filter change re-runs the search immediately (SPEC section 7.2): the query embedding is
  // cached, so this costs no extra provider quota. It replaces the current history entry rather
  // than adding one, so the back button steps through searches, not every filter click.
  function updateTypes(next: MediaType[]) {
    setTypes(next);
    if (!request.query) return;
    window.history.replaceState(null, "", urlFor(request.query, next, eras));
    setRequest((current) => ({ ...current, types: next, id: current.id + 1 }));
  }

  function updateEras(next: Era[]) {
    setEras(next);
    if (!request.query) return;
    window.history.replaceState(null, "", urlFor(request.query, types, next));
    setRequest((current) => ({ ...current, eras: next, id: current.id + 1 }));
  }

  function retry() {
    setRequest((current) => ({ ...current, id: current.id + 1 }));
  }

  const searched = request.query !== "";
  const current = searched && outcome?.requestId === request.id ? outcome : null;
  const loading = searched && current === null;

  return (
    <section>
      <form onSubmit={handleSubmit} role="search" className="flex gap-2">
        <label htmlFor="query" className="sr-only">
          Describe a feeling
        </label>
        <input
          id="query"
          name="q"
          type="search"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={MAX_QUERY_LENGTH}
          placeholder="Describe a feeling, like a rainy night drive"
          aria-describedby="data-notice"
          className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2"
        />
        <button
          type="submit"
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white"
        >
          Search
        </button>
      </form>
      <p id="data-notice" className="mt-2 text-xs text-gray-500">
        Your search text is sent to Google&apos;s Gemini API (free tier) to find matches. Google may
        keep it and have people review it, so please don&apos;t include personal information.{" "}
        <a
          href="https://ai.google.dev/gemini-api/terms"
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          Gemini API terms
        </a>
      </p>

      <SearchFilters types={types} eras={eras} onTypesChange={updateTypes} onErasChange={updateEras} />

      <div className="mt-6">
        {loading && <p role="status">Searching…</p>}

        {current?.kind === "error" && (
          <div role="alert" className="flex flex-col items-start gap-2">
            <p>{current.message}</p>
            <button type="button" onClick={retry} className="text-sm underline">
              Try again
            </button>
          </div>
        )}

        {current?.kind === "response" && (
          <ResultsList
            response={current.response}
            singleType={request.types.length === 1 ? request.types[0] : null}
          />
        )}
      </div>
    </section>
  );
}
