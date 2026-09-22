import { useEffect, useState } from "react";
import type { ItemDetail, ItemScore, MediaType, ResultGroup } from "./api";
import { getItem, getSimilarItems, SearchError } from "./api";
import Link from "./Link";
import { ASPECT, PLACEHOLDER } from "./ResultCard";
import { Grid } from "./ResultsList";

const TYPE_LABEL: Record<MediaType, string> = { film: "Film", game: "Game", album: "Album" };

const SCORE_LABEL: Record<string, { label: string; scale?: number; decimals: number }> = {
  tmdb: { label: "TMDB score", scale: 10, decimals: 1 },
  igdb: { label: "IGDB rating", scale: 100, decimals: 0 },
};

function formatScore(score: ItemScore): string {
  const known = SCORE_LABEL[score.source];
  const label = known?.label ?? score.source;
  const value = (known ? score.value : Math.round(score.value * 10) / 10).toFixed(
    known?.decimals ?? 1,
  );
  const scale = known?.scale ? `/${known.scale}` : "";
  const votes = score.voteCount !== null ? ` (${score.voteCount.toLocaleString()} votes)` : "";
  return `${label}: ${value}${scale}${votes}`;
}

function metadataLines(item: ItemDetail): string[] {
  const { mediaType, details } = item;
  const lines: string[] = [];
  if (mediaType === "album" && details.artist) lines.push(`By: ${details.artist}`);
  if (details.genres.length > 0) lines.push(`Genres: ${details.genres.join(", ")}`);
  if (mediaType === "game" && details.themes.length > 0) {
    lines.push(`Themes: ${details.themes.join(", ")}`);
  }
  if (mediaType !== "album" && details.keywords.length > 0) {
    lines.push(`Keywords: ${details.keywords.join(", ")}`);
  }
  if (mediaType === "album" && details.tags.length > 0) lines.push(`Tags: ${details.tags.join(", ")}`);
  return lines;
}

function Cover({ item }: { item: ItemDetail }) {
  return (
    <div
      className={`w-full max-w-xs overflow-hidden rounded-md bg-gray-200 ${ASPECT[item.mediaType]}`}
    >
      {item.coverUrl ? (
        <img
          src={item.coverUrl}
          alt={`${TYPE_LABEL[item.mediaType]} cover for ${item.title}`}
          referrerPolicy="no-referrer"
          // See ResultCard: fitted inside the box, never cropped to fill it.
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="flex h-full items-center justify-center p-2 text-center text-sm text-gray-500">
          {PLACEHOLDER[item.mediaType]}
        </div>
      )}
    </div>
  );
}

function Summary({ item }: { item: ItemDetail }) {
  if (item.mediaType === "album" && !item.summary) {
    return <p className="text-gray-500">No summary available for this album.</p>;
  }
  if (!item.summary) return null;
  return (
    <div>
      <p>{item.summary}</p>
      {item.details.wikipedia && (
        <p className="mt-2 text-xs text-gray-500">
          Source:{" "}
          <a
            href={item.details.wikipedia.url}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            {item.details.wikipedia.title} on Wikipedia
          </a>
          , available under{" "}
          <a
            href="https://creativecommons.org/licenses/by-sa/4.0/"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            CC BY-SA 4.0
          </a>
          .
        </p>
      )}
    </div>
  );
}

function MoreLikeThis({ groups }: { groups: ResultGroup[] }) {
  const nonEmpty = groups.filter((group) => group.results.length > 0);
  if (nonEmpty.length === 0) return null;
  return (
    <section className="mt-10">
      <h2 className="mb-4 text-lg font-medium">More like this</h2>
      <div className="flex flex-col gap-8">
        {nonEmpty.map((group) => (
          <div key={group.mediaType}>
            <h3 className="mb-3 text-sm font-medium text-gray-500">
              {TYPE_LABEL[group.mediaType]}s
            </h3>
            <Grid results={group.results} showBadge={nonEmpty.length > 1} />
          </div>
        ))}
      </div>
    </section>
  );
}

type Outcome =
  | { id: number; kind: "error"; message: string; notFound: boolean }
  | { id: number; kind: "ready"; item: ItemDetail; similar: ResultGroup[] };

export default function ItemPage({ id, query }: { id: number; query?: string }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getItem(id, { query, signal: controller.signal }).then(
      (item) => {
        if (controller.signal.aborted) return;
        getSimilarItems(id, controller.signal).then(
          (similar) => {
            if (!controller.signal.aborted) setOutcome({ id, kind: "ready", item, similar });
          },
          () => {
            // "More like this" is a secondary feature: its own failure should not sink the page.
            if (!controller.signal.aborted) setOutcome({ id, kind: "ready", item, similar: [] });
          },
        );
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setOutcome({
          id,
          kind: "error",
          message:
            error instanceof SearchError ? error.message : "Something went wrong. Please try again.",
          notFound: error instanceof SearchError && error.kind === "invalid",
        });
      },
    );
    return () => controller.abort();
  }, [id, query, retryToken]);

  // A newer id (a "more like this" click while this page was still loading) makes a stale
  // outcome's answer invalid, the same way SearchPage guards against a slow, superseded search.
  const state = outcome?.id === id ? outcome : { kind: "loading" as const };

  return (
    <section>
      <Link to="/" className="text-sm underline">
        ← Search
      </Link>

      {state.kind === "loading" && (
        <p role="status" className="mt-6">
          Loading…
        </p>
      )}

      {state.kind === "error" && (
        <div role="alert" className="mt-6 flex flex-col items-start gap-2">
          <p>{state.message}</p>
          {!state.notFound && (
            <button
              type="button"
              onClick={() => setRetryToken((t) => t + 1)}
              className="text-sm underline"
            >
              Try again
            </button>
          )}
        </div>
      )}

      {state.kind === "ready" && (
        <div className="mt-6">
          {/* items-start: without it, flexbox's default cross-axis stretch forces the cover to
              match the text column's height, ignoring its own aspect ratio — a long summary made
              the cover box balloon into a huge gray rectangle around a small, centered image. */}
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
            <Cover item={state.item} />
            <div className="flex-1">
              <p className="text-xs uppercase tracking-wide text-gray-500">
                {TYPE_LABEL[state.item.mediaType]}
              </p>
              <h2 className="text-2xl font-semibold">{state.item.title}</h2>
              <p className="text-sm text-gray-500">{state.item.releaseYear ?? "Year unknown"}</p>

              {state.item.explanation && (
                <p className="mt-2 text-sm italic text-gray-600">{state.item.explanation}</p>
              )}

              {state.item.scores.length > 0 && (
                <ul className="mt-2 text-sm text-gray-700">
                  {state.item.scores.map((score) => (
                    <li key={score.source}>{formatScore(score)}</li>
                  ))}
                </ul>
              )}

              {metadataLines(state.item).length > 0 && (
                <ul className="mt-3 text-sm text-gray-600">
                  {metadataLines(state.item).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}

              <div className="mt-4">
                <Summary item={state.item} />
              </div>
            </div>
          </div>

          <MoreLikeThis groups={state.similar} />
        </div>
      )}
    </section>
  );
}
