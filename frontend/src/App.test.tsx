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
