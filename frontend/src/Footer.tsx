// Official TMDB logo, used unmodified (only the height is set, so the aspect ratio is preserved).
const TMDB_LOGO =
  "https://www.themoviedb.org/assets/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg";

export default function Footer() {
  return (
    <footer className="mt-12 flex flex-col items-center gap-2 border-t border-gray-200 py-6 text-center text-xs text-gray-500">
      <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer">
        <img src={TMDB_LOGO} alt="TMDB" height={12} referrerPolicy="no-referrer" className="h-3" />
      </a>
      <p>Film data and posters come from TMDB.</p>
      <p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </footer>
  );
}
