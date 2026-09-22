import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import SearchPage from "./SearchPage";
import {
  blendedBody,
  deferred,
  groupedBody,
  jsonResponse,
  rawFilm,
  rawGame,
  stubFetch,
} from "./test-utils";

function search(text: string) {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
}

function urlOf(fetchMock: ReturnType<typeof stubFetch>, callIndex = 0): URL {
  return new URL(fetchMock.mock.calls[callIndex][0], "http://localhost");
}

function okWith(...results: unknown[]) {
  return stubFetch((url) => {
    const q = new URL(url, "http://localhost").searchParams.get("q") ?? "";
    return Promise.resolve(jsonResponse(blendedBody(q, results)));
  });
}

test("starts idle with the search box, the data-use notice, and every type enabled", () => {
  const fetchMock = okWith();

  render(<SearchPage />);

  const box = screen.getByRole("searchbox", { name: "Describe a feeling" });
  expect(box).toHaveValue("");
  expect(box).toHaveAttribute("maxlength", "200");
  expect(screen.getByText(/sent to Google's Gemini API/)).toBeInTheDocument();
  expect(box).toHaveAccessibleDescription(/Gemini API \(free tier\)/);
  const terms = screen.getByRole("link", { name: "Gemini API terms" });
  expect(terms).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  expect(screen.getByRole("checkbox", { name: "Films" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Games" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Albums" })).toBeChecked();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("searching shows a loading state, then the results, with no types param by default", async () => {
  const fetchMock = okWith(rawFilm(1, { title: "Neon Rain Drive" }), rawGame(2));
  render(<SearchPage />);

  search("a rainy night drive");

  expect(screen.getByRole("status")).toHaveTextContent("Searching");
  expect(await screen.findByText("Neon Rain Drive")).toBeInTheDocument();
  const url = urlOf(fetchMock);
  expect(url.pathname + url.search).toBe("/api/search/?q=a+rainy+night+drive");
  expect(url.searchParams.has("types")).toBe(false);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("the search, but not the default filters, is written to the URL", async () => {
  okWith(rawFilm(1));
  render(<SearchPage />);

  search("night & fog");
  await screen.findByText("Film 1");

  expect(window.location.pathname).toBe("/search");
  const params = new URLSearchParams(window.location.search);
  expect(params.get("q")).toBe("night & fog");
  expect(params.has("types")).toBe(false);
  expect(params.has("eras")).toBe(false);
});

test("a query already in the URL is searched on load", async () => {
  window.history.replaceState(null, "", "/search?q=night%20drive");
  const fetchMock = okWith(rawFilm(1));

  render(<SearchPage />);

  expect(screen.getByRole("searchbox")).toHaveValue("night drive");
  expect(await screen.findByText("Film 1")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("types and eras already in the URL are honored on load and sent to the API", async () => {
  window.history.replaceState(null, "", "/search?q=drive&types=game%2Calbum&eras=1980-1989");
  const fetchMock = okWith();

  render(<SearchPage />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());

  expect(screen.getByRole("checkbox", { name: "Films" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Games" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Albums" })).toBeChecked();
  expect(screen.getByRole("button", { name: "80s" })).toHaveAttribute("aria-pressed", "true");
  const url = urlOf(fetchMock);
  expect(url.searchParams.get("types")).toBe("game,album");
  expect(url.searchParams.get("eras")).toBe("1980-1989");
});

test("a blank search does nothing", () => {
  const fetchMock = okWith();
  render(<SearchPage />);

  search("   ");

  expect(fetchMock).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(window.location.pathname).toBe("/");
});

test("no results gets a helpful message", async () => {
  okWith();
  render(<SearchPage />);

  search("zzzz");

  expect(await screen.findByText(/Nothing matched that yet/)).toBeInTheDocument();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

test.each([
  ["a rejected query", () => jsonResponse({ detail: "Query is too long (maximum 200 characters)." }, 400), /too long/],
  ["an outage", () => jsonResponse({ detail: "x" }, 503), /temporarily unavailable/],
])("%s shows an alert and can be retried", async (_name, failing, expected) => {
  let calls = 0;
  const fetchMock = stubFetch(() => {
    calls += 1;
    return Promise.resolve(calls === 1 ? failing() : jsonResponse(blendedBody("x", [rawFilm(7)])));
  });
  render(<SearchPage />);

  search("x");

  expect(await screen.findByRole("alert")).toHaveTextContent(expected);
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Film 7")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("a network failure shows a connection message", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
  render(<SearchPage />);

  search("x");

  expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the server/);
});

test("a slow older search never overwrites a newer one", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  stubFetch((url) => (url.includes("q=one") ? first.promise : second.promise));
  render(<SearchPage />);

  search("one");
  search("two");
  second.resolve(jsonResponse(blendedBody("two", [rawFilm(2, { title: "Result Two" })])));
  expect(await screen.findByText("Result Two")).toBeInTheDocument();
  first.resolve(jsonResponse(blendedBody("one", [rawFilm(1, { title: "Result One" })])));
  await first.promise;

  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(screen.getByText("Result Two")).toBeInTheDocument();
  expect(screen.queryByText("Result One")).not.toBeInTheDocument();
});

test("going back re-runs the earlier search from the URL", async () => {
  const fetchMock = okWith(rawFilm(1));
  render(<SearchPage />);
  search("one");
  await screen.findByText("Film 1");

  window.history.replaceState(null, "", "/search?q=two");
  window.dispatchEvent(new PopStateEvent("popstate"));

  await waitFor(() => expect(screen.getByRole("searchbox")).toHaveValue("two"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(urlOf(fetchMock, 1).searchParams.get("q")).toBe("two");
});

test("going back to the landing page clears the results", async () => {
  okWith(rawFilm(1));
  render(<SearchPage />);
  search("one");
  await screen.findByText("Film 1");

  window.history.replaceState(null, "", "/");
  window.dispatchEvent(new PopStateEvent("popstate"));

  await waitFor(() => expect(screen.queryByText("Film 1")).not.toBeInTheDocument());
  expect(screen.getByRole("searchbox")).toHaveValue("");
});

// --- filters re-run the search immediately -----------------------------------------------------

test("toggling a type after searching re-runs the search and updates the url", async () => {
  const fetchMock = okWith(rawFilm(1));
  render(<SearchPage />);
  search("x");
  await screen.findByText("Film 1");

  fireEvent.click(screen.getByRole("checkbox", { name: "Games" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(urlOf(fetchMock, 1).searchParams.get("types")).toBe("film,album");
  expect(new URLSearchParams(window.location.search).get("types")).toBe("film,album");
  expect(window.location.pathname).toBe("/search");
});

test("toggling a type before any search does not fetch anything", () => {
  const fetchMock = okWith();
  render(<SearchPage />);

  fireEvent.click(screen.getByRole("checkbox", { name: "Games" }));

  expect(fetchMock).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe("/");
});

test("clicking a decade after searching re-runs the search with the era", async () => {
  const fetchMock = okWith(rawFilm(1));
  render(<SearchPage />);
  search("x");
  await screen.findByText("Film 1");

  fireEvent.click(screen.getByRole("button", { name: "80s" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(urlOf(fetchMock, 1).searchParams.get("eras")).toBe("1980-1989");
});

test("a filter change replaces the history entry rather than adding one", async () => {
  okWith(rawFilm(1));
  render(<SearchPage />);
  search("x");
  await screen.findByText("Film 1");
  const before = window.history.length;

  fireEvent.click(screen.getByRole("checkbox", { name: "Games" }));
  await waitFor(() => expect(new URLSearchParams(window.location.search).get("types")).toBe("film,album"));

  expect(window.history.length).toBe(before);
});

// --- layouts and the fallback notice, wired end to end ------------------------------------------

test("a grouped response renders its sections", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        groupedBody("x", [
          { media_type: "film", results: [rawFilm(1)] },
          { media_type: "game", results: [] },
        ]),
      ),
    ),
  );
  render(<SearchPage />);

  search("x");

  expect(await screen.findByRole("heading", { name: "Films" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Games" })).toBeInTheDocument();
  expect(screen.getByText(/No games matched/)).toBeInTheDocument();
});

test("a fallback notice from the API is shown to the visitor", async () => {
  stubFetch(() =>
    Promise.resolve(
      jsonResponse(
        blendedBody("x", [rawFilm(1)], {
          notices: ["Vibe search is temporarily unavailable, so these are text matches instead."],
          mode: "text",
        }),
      ),
    ),
  );
  render(<SearchPage />);

  search("x");

  expect(await screen.findByText(/temporarily unavailable/)).toBeInTheDocument();
});
