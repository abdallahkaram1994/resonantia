import Footer from "./Footer";
import ItemPage from "./ItemPage";
import Link from "./Link";
import { useLocation } from "./router";
import SearchPage from "./SearchPage";

const ITEM_PATH = /^\/item\/(\d+)(?:\/|$)/;

export default function App() {
  const location = useLocation();
  const itemId = ITEM_PATH.exec(location)?.[1];

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4 py-8">
      <header className="mb-6 text-center">
        <Link to="/" className="inline-block">
          <h1 className="text-3xl font-semibold">Resonantia</h1>
        </Link>
        <p className="text-sm text-gray-500">Describe a feeling and find matches that fit it.</p>
      </header>
      <main className="flex-1">
        {itemId !== undefined ? <ItemPage id={Number(itemId)} /> : <SearchPage />}
      </main>
      <Footer />
    </div>
  );
}
