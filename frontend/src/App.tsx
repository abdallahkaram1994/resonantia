import Footer from "./Footer";
import SearchPage from "./SearchPage";

export default function App() {
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4 py-8">
      <header className="mb-6 text-center">
        <h1 className="text-3xl font-semibold">Resonantia</h1>
        <p className="text-sm text-gray-500">Describe a feeling and find films that match it.</p>
      </header>
      <main className="flex-1">
        <SearchPage />
      </main>
      <Footer />
    </div>
  );
}
