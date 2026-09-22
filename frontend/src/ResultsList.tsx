import type { ReactNode } from "react";
import type { MediaType, SearchResponse, SearchResult } from "./api";
import ResultCard from "./ResultCard";

const TYPE_LABEL: Record<MediaType, string> = { film: "Films", game: "Games", album: "Albums" };
const TYPE_LABEL_LOWER: Record<MediaType, string> = {
  film: "films",
  game: "games",
  album: "albums",
};

function EmptyMessage({ children }: { children: ReactNode }) {
  return <p role="status">{children}</p>;
}

export default function ResultsList({
  response,
  singleType,
}: {
  response: SearchResponse;
  // The one enabled type, when `response.layout` is "single" (zero results carry no media type
  // of their own to read it back from).
  singleType: MediaType | null;
}) {
  const { layout, mode, notices, query } = response;

  return (
    <div>
      {notices.length > 0 && (
        <div role="status" className="mb-4 flex flex-col gap-1">
          {notices.map((notice) => (
            <p
              key={notice}
              className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
            >
              {notice}
            </p>
          ))}
        </div>
      )}

      {layout === "single" && (
        <>
          <h2 className="mb-4 text-sm text-gray-500">
            {singleType ? TYPE_LABEL[singleType] : "Results"} for “{query}”
          </h2>
          {response.results.length === 0 ? (
            <EmptyMessage>
              No {singleType ? TYPE_LABEL_LOWER[singleType] : "items"} matched that yet. Try
              describing the mood in different words.
            </EmptyMessage>
          ) : (
            <Grid results={response.results} />
          )}
        </>
      )}

      {layout === "blended" && (
        <>
          <h2 className="mb-4 text-sm text-gray-500">Results for “{query}”</h2>
          {response.results.length === 0 ? (
            <EmptyMessage>
              Nothing matched that yet. Try describing the mood in different words.
            </EmptyMessage>
          ) : (
            <Grid results={response.results} showBadge />
          )}
        </>
      )}

      {layout === "grouped" && (
        <>
          <h2 className="mb-4 text-sm text-gray-500">
            {mode === "text" ? "Text matches" : "Results"} for “{query}”
          </h2>
          <div className="flex flex-col gap-8">
            {response.groups.map((group) => (
              <section key={group.mediaType}>
                <h3 className="mb-3 text-base font-medium">{TYPE_LABEL[group.mediaType]}</h3>
                {group.results.length === 0 ? (
                  <EmptyMessage>
                    No {TYPE_LABEL_LOWER[group.mediaType]} matched that yet.
                  </EmptyMessage>
                ) : (
                  <Grid results={group.results} />
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function Grid({
  results,
  showBadge = false,
}: {
  results: SearchResult[];
  showBadge?: boolean;
}) {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
      {results.map((result) => (
        <ResultCard key={result.id} result={result} showBadge={showBadge} />
      ))}
    </ul>
  );
}
