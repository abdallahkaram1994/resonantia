import { useState } from "react";
import type { SearchResult } from "./api";

export default function ResultCard({ result }: { result: SearchResult }) {
  const [imageFailed, setImageFailed] = useState(false);
  const showPoster = result.coverUrl !== null && !imageFailed;

  return (
    <li className="flex flex-col gap-2">
      <div className="aspect-[2/3] overflow-hidden rounded-md bg-gray-200">
        {showPoster ? (
          <img
            src={result.coverUrl ?? undefined}
            alt={`Poster for ${result.title}`}
            loading="lazy"
            // The page URL contains the search text, so never send it to the image host.
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center p-2 text-center text-xs text-gray-500">
            No poster
          </div>
        )}
      </div>
      <div>
        <p className="text-sm font-medium leading-tight">{result.title}</p>
        <p className="text-xs text-gray-500">{result.releaseYear ?? "Year unknown"}</p>
      </div>
    </li>
  );
}
