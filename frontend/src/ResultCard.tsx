import { useState } from "react";
import type { MediaType, SearchResult } from "./api";
import Link from "./Link";

// Each source's own image shape, confirmed by reading real files: TMDB posters (w342) are
// 342x513, exactly 2:3; IGDB covers (t_cover_big) are 264x352, exactly 3:4 — visibly stubbier
// than a film poster, not close enough to share its box; Cover Art Archive images are 500x500.
export const ASPECT: Record<MediaType, string> = {
  film: "aspect-[2/3]",
  game: "aspect-[3/4]",
  album: "aspect-square",
};

export const PLACEHOLDER: Record<MediaType, string> = {
  film: "No poster",
  game: "No cover",
  album: "No art",
};

export const BADGE: Record<MediaType, string> = { film: "Film", game: "Game", album: "Album" };

export default function ResultCard({
  result,
  showBadge = false,
  query,
}: {
  result: SearchResult;
  showBadge?: boolean;
  // The search this result came from, if any. Carried into the item's link as `?q=` so its
  // detail page can show a match explanation (see api.ts's getItem); left out for a result with
  // no originating search, such as "more like this" on another item's page.
  query?: string;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const showCover = result.coverUrl !== null && !imageFailed;
  const to = query
    ? `/item/${result.id}?${new URLSearchParams({ q: query })}`
    : `/item/${result.id}`;

  return (
    <li className="flex flex-col gap-2">
      <Link to={to} className="flex flex-col gap-2">
        <div
          className={`relative overflow-hidden rounded-md bg-gray-200 ${ASPECT[result.mediaType]}`}
        >
          {showCover ? (
            <img
              src={result.coverUrl ?? undefined}
              alt={`${BADGE[result.mediaType]} cover for ${result.title}`}
              loading="lazy"
              // The page URL contains the search text, so never send it to the image host.
              referrerPolicy="no-referrer"
              onError={() => setImageFailed(true)}
              // A source image's real proportions do not always match its type's usual box (an
              // IGDB cover in particular can be almost any shape), so it is fitted inside the box
              // rather than cropped to fill it: never zoomed into the middle, just letterboxed.
              className="h-full w-full object-contain"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-2 text-center text-xs text-gray-500">
              {PLACEHOLDER[result.mediaType]}
            </div>
          )}
          {showBadge && (
            <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white">
              {BADGE[result.mediaType]}
            </span>
          )}
        </div>
        <div>
          <p className="text-sm font-medium leading-tight">{result.title}</p>
          <p className="text-xs text-gray-500">{result.releaseYear ?? "Year unknown"}</p>
        </div>
      </Link>
    </li>
  );
}
