import Footer from "./Footer";
import ItemPage from "./ItemPage";
import Link from "./Link";
import { useLocation } from "./router";
import SearchPage from "./SearchPage";

// The id is followed by a trailing slash, a `?q=...`, or nothing (end of string).
const ITEM_PATH = /^\/item\/(\d+)(?:[/?]|$)/;

// The search an item link was opened from, if any (see ResultCard/Grid), read back out of the
// URL so ItemPage can ask for a match explanation. `location` is already `pathname + search`.
function queryParam(location: string): string | undefined {
  const question = location.indexOf("?");
  if (question === -1) return undefined;
  return new URLSearchParams(location.slice(question)).get("q") ?? undefined;
}

export default function App() {
  const location = useLocation();
  const itemId = ITEM_PATH.exec(location)?.[1];
  const itemQuery = itemId !== undefined ? queryParam(location) : undefined;

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4 py-8">
      <header className="mb-6 text-center">
        <Link to="/" className="inline-block">
          <h1 className="text-3xl font-semibold">Resonantia</h1>
        </Link>
        <p className="text-sm text-gray-500">Describe a feeling and find matches that fit it.</p>
      </header>
      <main className="flex-1">
        {itemId !== undefined ? (
          <ItemPage id={Number(itemId)} query={itemQuery} />
        ) : (
          <SearchPage />
        )}
      </main>
      <Footer />
    </div>
  );
}
