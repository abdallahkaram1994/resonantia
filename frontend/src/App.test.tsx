import { render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";
import { jsonResponse, rawItemDetail, stubFetch } from "./test-utils";

test("the page has the product name, the search box and the TMDB attribution", () => {
  stubFetch(() => Promise.resolve(jsonResponse({ query: "", layout: "single", mode: "vibe", notices: [], results: [] })));

  render(<App />);

  expect(screen.getByRole("heading", { level: 1, name: "Resonantia" })).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toHaveTextContent(/not endorsed or certified by TMDB/);
});

test("the product name links back to the landing page", () => {
  render(<App />);

  expect(screen.getByRole("link", { name: "Resonantia" })).toHaveAttribute("href", "/");
});

test("an /item/<id> url renders the item detail page, not the search page", async () => {
  window.history.replaceState(null, "", "/item/5");
  stubFetch((url) =>
    Promise.resolve(
      url.includes("/similar/")
        ? jsonResponse({ groups: [] })
        : jsonResponse(rawItemDetail({ id: 5, title: "The Detail Item" })),
    ),
  );

  render(<App />);

  expect(await screen.findByRole("heading", { name: "The Detail Item" })).toBeInTheDocument();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
});

test("an /item/<id>?q=... url still renders the item detail page, not search", async () => {
  // Regression: the item-path regex originally required a `/` or end-of-string right after the
  // id, so a result card's own `?q=` link (added for match explanations) failed to match at all,
  // silently falling through to the search page instead.
  window.history.replaceState(null, "", "/item/5?q=a+rainy+night+drive");
  const fetchMock = stubFetch((url) =>
    Promise.resolve(
      url.includes("/similar/")
        ? jsonResponse({ groups: [] })
        : jsonResponse(rawItemDetail({ id: 5, title: "The Detail Item" })),
    ),
  );

  render(<App />);

  expect(await screen.findByRole("heading", { name: "The Detail Item" })).toBeInTheDocument();
  expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  const detailCall = fetchMock.mock.calls.find((c) => !String(c[0]).includes("/similar/"));
  expect(new URL(String(detailCall?.[0]), "http://localhost").searchParams.get("q")).toBe(
    "a rainy night drive",
  );
});

test("any other path renders the search page", () => {
  window.history.replaceState(null, "", "/search?q=rain");

  render(<App />);

  expect(screen.getByRole("searchbox")).toBeInTheDocument();
});

test("navigating back from an item page to search is picked up", async () => {
  window.history.replaceState(null, "", "/item/5");
  stubFetch((url) =>
    Promise.resolve(url.includes("/similar/") ? jsonResponse({ groups: [] }) : jsonResponse(rawItemDetail())),
  );
  render(<App />);
  await screen.findByRole("heading", { name: "The Film" });

  window.history.replaceState(null, "", "/");
  window.dispatchEvent(new PopStateEvent("popstate"));

  await waitFor(() => expect(screen.getByRole("searchbox")).toBeInTheDocument());
});
