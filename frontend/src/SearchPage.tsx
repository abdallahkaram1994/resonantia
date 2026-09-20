import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { search, SearchError } from "./api";
import type { SearchResult } from "./api";
import ResultCard from "./ResultCard";

const MAX_QUERY_LENGTH = 200;

type SearchRequest = { query: string; id: number };
type Outcome =
  | { requestId: number; kind: "results"; results: SearchResult[] }
  | { requestId: number; kind: "error"; message: string };

function queryFromUrl(): string {
  return (new URLSearchParams(window.location.search).get("q") ?? "").trim();
}

function urlFor(query: string): string {
  return query ? `/search?q=${encodeURIComponent(query)}` : "/";
}

export default function SearchPage() {
  const [input, setInput] = useState(queryFromUrl);
  const [request, setRequest] = useState<SearchRequest>(() => ({ query: queryFromUrl(), id: 0 }));
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (!request.query) return;
    const controller = new AbortController();
    search(request.query, controller.signal).then(
      (response) => {
        // A newer search has replaced this one, so its late answer must not overwrite the page.
        if (controller.signal.aborted) return;
        setOutcome({ requestId: request.id, kind: "results", results: response.results });
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
      const query = queryFromUrl();
      setInput(query);
      setRequest((current) => ({ query, id: current.id + 1 }));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = input.trim();
    if (!query) return;
    window.history.pushState(null, "", urlFor(query));
    setRequest((current) => ({ query, id: current.id + 1 }));
  }

  function retry() {
    setRequest((current) => ({ query: current.query, id: current.id + 1 }));
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

        {current?.kind === "results" && current.results.length === 0 && (
          <p role="status">
            No films matched that yet. Try describing the mood in different words.
          </p>
        )}

        {current?.kind === "results" && current.results.length > 0 && (
          <>
            <h2 className="mb-4 text-sm text-gray-500">Films for “{request.query}”</h2>
            <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
              {current.results.map((result) => (
                <ResultCard key={result.id} result={result} />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
