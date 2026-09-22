import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { SearchResponse, SearchResult } from "./api";
import ResultsList from "./ResultsList";

function result(id: number, overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id,
    mediaType: "film",
    title: `Item ${id}`,
    releaseYear: 2001,
    coverUrl: null,
    ...overrides,
  };
}

type Common = { query: string; mode: "vibe" | "text"; notices: string[] };
const COMMON: Common = { query: "x", mode: "vibe", notices: [] };

function single(results: SearchResult[], overrides: Partial<Common> = {}): SearchResponse {
  return { ...COMMON, ...overrides, layout: "single", results };
}

function blended(results: SearchResult[], overrides: Partial<Common> = {}): SearchResponse {
  return { ...COMMON, ...overrides, layout: "blended", results };
}

function grouped(
  groups: { mediaType: "film" | "game" | "album"; results: SearchResult[] }[],
  overrides: Partial<Common> = {},
): SearchResponse {
  return { ...COMMON, ...overrides, layout: "grouped", groups };
}

test("a single layout is headed by the one type and the query", () => {
  render(<ResultsList response={single([result(1)])} singleType="game" />);

  expect(screen.getByRole("heading", { name: "Games for “x”" })).toBeInTheDocument();
  expect(screen.getByText("Item 1")).toBeInTheDocument();
});

test.each([
  ["single", single([result(1)])],
  ["blended", blended([result(1)])],
  ["grouped", grouped([{ mediaType: "film", results: [result(1)] }])],
])(
  "a %s layout links each result to its detail page with the search's own query",
  (_name, response) => {
    render(<ResultsList response={response} singleType="film" />);

    expect(screen.getByRole("link", { name: /Item 1/ })).toHaveAttribute(
      "href",
      "/item/1?q=x",
    );
  },
);

test("no results in a single layout gets a type-specific message", () => {
  render(<ResultsList response={single([])} singleType="album" />);

  expect(screen.getByText(/No albums matched that yet/)).toBeInTheDocument();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});

test("a blended layout is headed generically and shows a badge per card", () => {
  render(<ResultsList response={blended([result(1), result(2, { mediaType: "game" })])} singleType={null} />);

  expect(screen.getByRole("heading", { name: "Results for “x”" })).toBeInTheDocument();
  expect(screen.getByText("Film")).toBeInTheDocument();
  expect(screen.getByText("Game")).toBeInTheDocument();
});

test("no results in a blended layout gets a generic message", () => {
  render(<ResultsList response={blended([])} singleType={null} />);

  expect(screen.getByText(/Nothing matched that yet/)).toBeInTheDocument();
});

test("a single layout never shows a type badge", () => {
  render(<ResultsList response={single([result(1)])} singleType="film" />);

  expect(screen.queryByText("Film")).not.toBeInTheDocument();
});

test("a grouped layout has one section per group, named type first", () => {
  render(
    <ResultsList
      response={grouped([
        { mediaType: "album", results: [result(1, { mediaType: "album" })] },
        { mediaType: "film", results: [result(2)] },
      ])}
      singleType={null}
    />,
  );

  const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(headings).toEqual(["Albums", "Films"]);
});

test("an empty group in a grouped layout still gets its own section and message", () => {
  render(
    <ResultsList
      response={grouped([
        { mediaType: "film", results: [result(1)] },
        { mediaType: "game", results: [] },
      ])}
      singleType={null}
    />,
  );

  expect(screen.getByText(/No games matched that yet/)).toBeInTheDocument();
  const gameSection = screen.getByRole("heading", { name: "Games" }).closest("section");
  expect(gameSection).not.toBeNull();
  expect(within(gameSection as HTMLElement).queryByRole("list")).not.toBeInTheDocument();
});

test("a grouped layout does not show per-card badges: the section heading already says the type", () => {
  render(
    <ResultsList
      response={grouped([{ mediaType: "film", results: [result(1)] }])}
      singleType={null}
    />,
  );

  const section = screen.getByRole("heading", { name: "Films" }).closest("section");
  expect(within(section as HTMLElement).queryByText("Film")).toBeNull();
});

test("no notices means no banner", () => {
  render(<ResultsList response={single([])} singleType="film" />);

  expect(screen.queryByText(/temporarily unavailable/)).not.toBeInTheDocument();
});

test("every notice from the response is shown", () => {
  render(
    <ResultsList
      response={single([], {
        notices: ["Vibe search is temporarily unavailable, so these are text matches instead."],
      })}
      singleType="film"
    />,
  );

  expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
});

test("a grouped layout mentions text mode in its heading", () => {
  render(
    <ResultsList
      response={grouped([{ mediaType: "film", results: [] }], { mode: "text" })}
      singleType={null}
    />,
  );

  expect(screen.getByRole("heading", { name: "Text matches for “x”" })).toBeInTheDocument();
});
