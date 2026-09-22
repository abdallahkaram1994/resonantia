import { useSyncExternalStore } from "react";

// No router library: the app has exactly two page shapes (search and item detail), so a page's
// own path plus the browser's native History API is enough. `navigate` updates the URL and lets
// every subscriber (this hook, wherever it is used) know, the same way a real back/forward
// navigation already does through the `popstate` event.

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function currentPath(): string {
  return window.location.pathname + window.location.search;
}

/** The current path and query string. Re-renders on navigation, including back/forward. */
export function useLocation(): string {
  return useSyncExternalStore(subscribe, currentPath);
}

/** Pushes a new URL and notifies every `useLocation` subscriber, including this one. */
export function navigate(path: string): void {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
