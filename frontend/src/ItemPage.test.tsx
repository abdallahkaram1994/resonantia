import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import ItemPage from "./ItemPage";
import { deferred, jsonResponse, rawFilm, rawGame, rawItemDetail, stubFetch } from "./test-utils";

function stubItem(
  detail: Record<string, unknown>,
  similarGroups: { media_type: string; results: unknown[] }[] = [],
) {
  return stubFetch((url) => {
    if (url.includes("/similar/")) {
      return Promise.resolve(jsonResponse({ groups: similarGroups }));
    }
    return Promise.resolve(jsonResponse(detail));
  });
}

test("shows loading, then the item's title, year and summary", async () => {
  stubItem(rawItemDetail({ title: "The Film", release_year: 1999, summary: "A great film." }));

  render(<ItemPage id={1} />);

  expect(screen.getByRole("status")).toHaveTextContent("Loading");
  expect(await screen.findByRole("heading", { name: "The Film" })).toBeInTheDocument();
  expect(screen.getByText("1999")).toBeInTheDocument();
  expect(screen.getByText("A great film.")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("fetches the detail and the similar items for the given id", async () => {
  const fetchMock = stubItem(rawItemDetail());

  render(<ItemPage id={42} />);
  await screen.findByRole("heading", { name: "The Film" });

  const urls = fetchMock.mock.calls.map((c) => c[0]);
  expect(urls).toContain("/api/items/42/");
  expect(urls).toContain("/api/items/42/similar/");
});

// --- match explanations (?q=, SPEC section 7.1/8) --------------------------------------------

test("an explanation is shown when the item was opened from a search", async () => {
  stubItem(rawItemDetail({ explanation: "Both follow a lonely night drive through the rain." }));

  render(<ItemPage id={1} query="a rainy night drive" />);

  expect(
    await screen.findByText("Both follow a lonely night drive through the rain."),
  ).toBeInTheDocument();
});

test("the query is sent to the backend as ?q=", async () => {
  const fetchMock = stubItem(rawItemDetail());

  render(<ItemPage id={1} query="a rainy night drive" />);
  await screen.findByRole("heading", { name: "The Film" });

  const detailCall = fetchMock.mock.calls.find((c) => !String(c[0]).includes("/similar/"));
  expect(new URL(String(detailCall?.[0]), "http://localhost").searchParams.get("q")).toBe(
    "a rainy night drive",
  );
});

test("with no query prop, nothing extra is shown and no q is sent", async () => {
  const fetchMock = stubItem(rawItemDetail());

  render(<ItemPage id={1} />);
  await screen.findByRole("heading", { name: "The Film" });

  const detailCall = fetchMock.mock.calls.find((c) => !String(c[0]).includes("/similar/"));
  expect(String(detailCall?.[0])).toBe("/api/items/1/");
});

test("a missing explanation from the backend shows nothing extra", async () => {
  stubItem(rawItemDetail());

  render(<ItemPage id={1} query="a rainy night drive" />);

  await screen.findByRole("heading", { name: "The Film" });
  expect(screen.queryByText(/./, { selector: "p.italic" })).not.toBeInTheDocument();
});

test("more like this links carry no query: those items were not reached by a search", async () => {
  stubItem(rawItemDetail({ explanation: "x" }), [
    { media_type: "film", results: [rawFilm(2)] },
  ]);

  render(<ItemPage id={1} query="a rainy night drive" />);
  await screen.findByRole("heading", { name: "More like this" });

  expect(screen.getByRole("link", { name: /Film 2/ })).toHaveAttribute("href", "/item/2");
});

test("a missing year is shown as unknown", async () => {
  stubItem(rawItemDetail({ release_year: null }));

  render(<ItemPage id={1} />);

  expect(await screen.findByText("Year unknown")).toBeInTheDocument();
});

test("a missing cover shows a type placeholder", async () => {
  stubItem(rawItemDetail({ cover_url: "" }));

  render(<ItemPage id={1} />);

  expect(await screen.findByText("No poster")).toBeInTheDocument();
});

test("a cover is fitted inside its box, never cropped to fill it", async () => {
  stubItem(rawItemDetail());

  render(<ItemPage id={1} />);

  const cover = await screen.findByAltText("Film cover for The Film");
  expect(cover).toHaveClass("object-contain");
  expect(cover).not.toHaveClass("object-cover");
});

test("a long summary cannot stretch the cover box off its own aspect ratio", async () => {
  // Flexbox stretches a row's children to match its tallest one by default, which was forcing
  // the cover box to grow far past its own aspect ratio next to a long summary, leaving a huge
  // gray rectangle around a small, centered image. items-start on the row is what stops it.
  stubItem(rawItemDetail({ summary: "A very long summary. ".repeat(80) }));

  render(<ItemPage id={1} />);
  const cover = await screen.findByAltText("Film cover for The Film");

  const row = cover.closest(".flex.flex-col.gap-6");
  expect(row).toHaveClass("sm:items-start");
});

test("scores are shown with their source label and vote count", async () => {
  stubItem(
    rawItemDetail({ scores: [{ source: "tmdb", value: 8.488, vote_count: 41215 }] }),
  );

  render(<ItemPage id={1} />);

  expect(await screen.findByText("TMDB score: 8.5/10 (41,215 votes)")).toBeInTheDocument();
});

test("an album has no scores shown, with no special-casing needed", async () => {
  stubItem(
    rawItemDetail({
      media_type: "album",
      details: { artist: "Band A", tags: [], wikipedia: null },
      scores: [],
    }),
  );

  render(<ItemPage id={1} />);

  await screen.findByRole("heading", { name: "The Film" });
  expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
});

test("game metadata shows genres, themes and keywords", async () => {
  stubItem(
    rawItemDetail({
      media_type: "game",
      details: {
        genres: ["Adventure"],
        themes: ["Open world"],
        keywords: ["survival"],
        tagline: "",
        runtime: null,
      },
      scores: [{ source: "igdb", value: 88.89, vote_count: 5982 }],
    }),
  );

  render(<ItemPage id={1} />);

  expect(await screen.findByText("Genres: Adventure")).toBeInTheDocument();
  expect(screen.getByText("Themes: Open world")).toBeInTheDocument();
  expect(screen.getByText("Keywords: survival")).toBeInTheDocument();
  expect(screen.getByText("IGDB rating: 89/100 (5,982 votes)")).toBeInTheDocument();
});

test("an album shows its artist as a byline and its tags, not keywords", async () => {
  stubItem(
    rawItemDetail({
      media_type: "album",
      title: "Studio One",
      details: { artist: "Band A", tags: ["indie", "night drive"], wikipedia: null },
      scores: [],
    }),
  );

  render(<ItemPage id={1} />);

  expect(await screen.findByText("By: Band A")).toBeInTheDocument();
  expect(screen.getByText("Tags: indie, night drive")).toBeInTheDocument();
  expect(screen.queryByText(/Keywords:/)).not.toBeInTheDocument();
});

test("an album with no summary gets the exact required message", async () => {
  stubItem(
    rawItemDetail({
      media_type: "album",
      summary: "",
      details: { artist: "Band A", tags: [], wikipedia: null },
      scores: [],
    }),
  );

  render(<ItemPage id={1} />);

  expect(await screen.findByText("No summary available for this album.")).toBeInTheDocument();
});

test("a film with a blank summary shows nothing extra, not the album message", async () => {
  stubItem(rawItemDetail({ summary: "" }));

  render(<ItemPage id={1} />);

  await screen.findByRole("heading", { name: "The Film" });
  expect(screen.queryByText(/No summary available/)).not.toBeInTheDocument();
});

test("an album's wikipedia summary is attributed with a CC BY-SA link", async () => {
  stubItem(
    rawItemDetail({
      media_type: "album",
      summary: "An album about rain.",
      details: {
        artist: "Band A",
        tags: [],
        wikipedia: { title: "Studio One", url: "https://en.wikipedia.org/wiki/Studio_One" },
      },
      scores: [],
    }),
  );

  render(<ItemPage id={1} />);
  await screen.findByText("An album about rain.");

  const source = screen.getByRole("link", { name: "Studio One on Wikipedia" });
  expect(source).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Studio_One");
  expect(screen.getByRole("link", { name: "CC BY-SA 4.0" })).toHaveAttribute(
    "href",
    "https://creativecommons.org/licenses/by-sa/4.0/",
  );
});

test("more like this shows a section per type that has matches", async () => {
  stubItem(rawItemDetail(), [
    { media_type: "film", results: [rawFilm(2, { title: "Similar Film" })] },
    { media_type: "game", results: [rawGame(3, { title: "Similar Game" })] },
    { media_type: "album", results: [] },
  ]);

  render(<ItemPage id={1} />);

  expect(await screen.findByRole("heading", { name: "More like this" })).toBeInTheDocument();
  expect(screen.getByText("Similar Film")).toBeInTheDocument();
  expect(screen.getByText("Similar Game")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Albums" })).not.toBeInTheDocument();
});

test("more like this links to the similar item's own detail page", async () => {
  stubItem(rawItemDetail(), [{ media_type: "film", results: [rawFilm(2)] }]);

  render(<ItemPage id={1} />);
  await screen.findByRole("heading", { name: "More like this" });

  expect(screen.getByRole("link", { name: /Film 2/ })).toHaveAttribute("href", "/item/2");
});

test("no similar items means no more-like-this section at all", async () => {
  stubItem(rawItemDetail(), []);

  render(<ItemPage id={1} />);

  await screen.findByRole("heading", { name: "The Film" });
  expect(screen.queryByRole("heading", { name: "More like this" })).not.toBeInTheDocument();
});

test("a failed similar-items fetch does not sink the rest of the page", async () => {
  stubFetch((url) => {
    if (url.includes("/similar/")) return Promise.resolve(new Response("nope", { status: 500 }));
    return Promise.resolve(jsonResponse(rawItemDetail()));
  });

  render(<ItemPage id={1} />);

  expect(await screen.findByRole("heading", { name: "The Film" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "More like this" })).not.toBeInTheDocument();
});

test("a missing item shows a not-found message with no retry button", async () => {
  stubFetch(() => Promise.resolve(jsonResponse({ detail: "Not found." }, 404)));

  render(<ItemPage id={999999} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("That item could not be found.");
  expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
});

test("an outage shows an alert that can be retried", async () => {
  let calls = 0;
  stubFetch((url) => {
    if (url.includes("/similar/")) return Promise.resolve(jsonResponse({ groups: [] }));
    calls += 1;
    return Promise.resolve(
      calls === 1 ? jsonResponse({ detail: "x" }, 503) : jsonResponse(rawItemDetail()),
    );
  });

  render(<ItemPage id={1} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));

  expect(await screen.findByRole("heading", { name: "The Film" })).toBeInTheDocument();
});

test("a network failure shows a connection message", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

  render(<ItemPage id={1} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the server/);
});

test("a slower earlier item's answer never overwrites a newer one", async () => {
  const first = deferred<Response>();
  const second = deferred<Response>();
  stubFetch((url) => {
    if (url.includes("/similar/")) return Promise.resolve(jsonResponse({ groups: [] }));
    return url.includes("/items/1/") ? first.promise : second.promise;
  });
  const { rerender } = render(<ItemPage id={1} />);

  rerender(<ItemPage id={2} />);
  second.resolve(jsonResponse(rawItemDetail({ id: 2, title: "Second Item" })));
  expect(await screen.findByRole("heading", { name: "Second Item" })).toBeInTheDocument();
  first.resolve(jsonResponse(rawItemDetail({ id: 1, title: "First Item" })));
  await first.promise;

  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(screen.getByRole("heading", { name: "Second Item" })).toBeInTheDocument();
});

test("a back link returns to the search page", async () => {
  stubItem(rawItemDetail());

  render(<ItemPage id={1} />);

  const back = screen.getByRole("link", { name: "← Search" });
  expect(back).toHaveAttribute("href", "/");
});

test("a hostile title is shown as text, never as HTML", async () => {
  const hostileTitle = "<img src=x onerror=alert(1)>";
  stubItem(rawItemDetail({ title: hostileTitle, cover_url: "" }));

  render(<ItemPage id={1} />);

  expect(await screen.findByText(hostileTitle)).toBeInTheDocument();
  expect(document.querySelector("img[src='x']")).toBeNull();
});
