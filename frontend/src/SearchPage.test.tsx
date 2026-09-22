import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import SearchPage from "./SearchPage";
import { deferred, jsonResponse, rawFilm, searchBody, stubFetch } from "./test-utils";

function search(text: string) {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
}

function okWith(...films: unknown[]) {
  return stubFetch((url) => {
    const q = new URL(url, "http://localhost").searchParams.get("q") ?? "";
    return Promise.resolve(jsonResponse(searchBody(q, films)));
  });
}

test("starts idle with the search box and the data-use notice", () => {
  const fetchMock = okWith();

  render(<SearchPage />);

  const box = screen.getByRole("searchbox", { name: "Describe a feeling" });
  expect(box).toHaveValue("");
  expect(box).toHaveAttribute("maxlength", "200");
  expect(screen.getByText(/sent to Google's Gemini API/)).toBeInTheDocument();
  expect(box).toHaveAccessibleDescription(/Gemini API \(free tier\)/);
  const terms = screen.getByRole("link", { name: "Gemini API terms" });
  expect(terms).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("searching shows a loading state, then the films with posters", async () => {
  const fetchMock = okWith(rawFilm(1, { title: "Neon Rain Drive" }), rawFilm(2));
  render(<SearchPage />);

  search("a rainy night drive");

  expect(screen.getByRole("status")).toHaveTextContent("Searching");
  expect(await screen.findByText("Neon Rain Drive")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/search/?q=a%20rainy%20night%20drive&types=film", {
    signal: expect.any(AbortSignal),
  });
  expect(screen.getByText("2001")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /a rainy night drive/ })).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  const poster = screen.getByAltText("Poster for Neon Rain Drive");
  expect(poster).toHaveAttribute("src", "https://image.tmdb.org/t/p/w342/film1.jpg");
  expect(poster).toHaveAttribute("loading", "lazy");
  expect(poster).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("the search is written to the URL", async () => {
  okWith(rawFilm(1));
  render(<SearchPage />);

  search("night & fog");
  await screen.findByText("Film 1");

  expect(window.location.pathname).toBe("/search");
  expect(new URLSearchParams(window.location.search).get("q")).toBe("night & fog");
});

test("a query already in the URL is searched on load", async () => {
  window.history.replaceState(null, "", "/search?q=night%20drive");
  const fetchMock = okWith(rawFilm(1));

  render(<SearchPage />);

  expect(screen.getByRole("searchbox")).toHaveValue("night drive");
  expect(await screen.findByText("Film 1")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/search/?q=night%20drive&types=film");
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

  expect(await screen.findByText(/No films matched that yet/)).toBeInTheDocument();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

test.each([
  ["a rejected query", () => jsonResponse({ detail: "Query is too long (maximum 200 characters)." }, 400), /too long/],
  ["an outage", () => jsonResponse({ detail: "x" }, 503), /temporarily unavailable/],
])("%s shows an alert and can be retried", async (_name, failing, expected) => {
  let calls = 0;
  const fetchMock = stubFetch(() => {
    calls += 1;
    return Promise.resolve(calls === 1 ? failing() : jsonResponse(searchBody("x", [rawFilm(7)])));
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
  second.resolve(jsonResponse(searchBody("two", [rawFilm(2, { title: "Result Two" })])));
  expect(await screen.findByText("Result Two")).toBeInTheDocument();
  first.resolve(jsonResponse(searchBody("one", [rawFilm(1, { title: "Result One" })])));
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
  expect(fetchMock.mock.calls[1][0]).toBe("/api/search/?q=two&types=film");
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

test("a missing poster shows a placeholder", async () => {
  okWith(rawFilm(1, { cover_url: "" }));
  render(<SearchPage />);

  search("x");

  expect(await screen.findByText("No poster")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("a poster that fails to load falls back to the placeholder", async () => {
  okWith(rawFilm(1));
  render(<SearchPage />);
  search("x");

  fireEvent.error(await screen.findByAltText("Poster for Film 1"));

  expect(screen.getByText("No poster")).toBeInTheDocument();
});

test("a cover on another host is never rendered", async () => {
  okWith(rawFilm(1, { cover_url: "https://tracker.example/pixel.gif" }));
  render(<SearchPage />);

  search("x");

  expect(await screen.findByText("No poster")).toBeInTheDocument();
  expect(document.querySelector("img[src*='tracker.example']")).toBeNull();
});

test("titles and queries are shown as text, never as HTML", async () => {
  const hostileTitle = "<img src=x onerror=alert(1)>";
  okWith(rawFilm(1, { title: hostileTitle, cover_url: "" }));
  render(<SearchPage />);

  search("<script>alert(1)</script>");

  expect(await screen.findByText(hostileTitle)).toBeInTheDocument();
  expect(screen.getByRole("heading")).toHaveTextContent("<script>alert(1)</script>");
  expect(document.querySelector("script")).toBeNull();
  expect(document.querySelector("img[src='x']")).toBeNull();
});
