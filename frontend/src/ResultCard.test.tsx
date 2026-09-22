import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { SearchResult } from "./api";
import ResultCard from "./ResultCard";

function film(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    id: 1,
    mediaType: "film",
    title: "The Film",
    releaseYear: 2001,
    coverUrl: "https://image.tmdb.org/t/p/w342/film1.jpg",
    ...overrides,
  };
}

test("renders the cover, title and year, linked to the item's detail page", () => {
  render(<ResultCard result={film()} />);

  const link = screen.getByRole("link", { name: /The Film/ });
  expect(link).toHaveAttribute("href", "/item/1");
  const cover = screen.getByAltText("Film cover for The Film");
  expect(cover).toHaveAttribute("src", "https://image.tmdb.org/t/p/w342/film1.jpg");
  expect(cover).toHaveAttribute("loading", "lazy");
  expect(cover).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(screen.getByText("The Film")).toBeInTheDocument();
  expect(screen.getByText("2001")).toBeInTheDocument();
});

test("a cover is fitted inside its box, never cropped to fill it", () => {
  // A source image's real proportions do not always match its type's usual box (an IGDB cover
  // especially can be almost any shape); object-cover would zoom into the middle and lose part
  // of it, so the cover must be letterboxed (object-contain) instead.
  render(<ResultCard result={film()} />);

  const cover = screen.getByAltText("Film cover for The Film");
  expect(cover).toHaveClass("object-contain");
  expect(cover).not.toHaveClass("object-cover");
});

test("an unknown year is shown as unknown, not blank", () => {
  render(<ResultCard result={film({ releaseYear: null })} />);

  expect(screen.getByText("Year unknown")).toBeInTheDocument();
});

test("a missing cover shows a placeholder instead", () => {
  render(<ResultCard result={film({ coverUrl: null })} />);

  expect(screen.getByText("No poster")).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("a cover that fails to load falls back to the placeholder", () => {
  render(<ResultCard result={film()} />);

  fireEvent.error(screen.getByAltText("Film cover for The Film"));

  expect(screen.getByText("No poster")).toBeInTheDocument();
});

test.each([
  ["game", "https://images.igdb.com/igdb/image/upload/t_cover_big/a.jpg", "No cover"],
  ["album", "https://coverartarchive.org/release-group/1/front-500", "No art"],
])("%s covers and placeholders use the type's own wording", (mediaType, coverUrl, placeholder) => {
  render(
    <ResultCard result={film({ mediaType: mediaType as SearchResult["mediaType"], coverUrl })} />,
  );

  expect(screen.getByAltText(new RegExp("cover for The Film"))).toHaveAttribute("src", coverUrl);
  render(
    <ResultCard
      result={film({ mediaType: mediaType as SearchResult["mediaType"], coverUrl: null })}
    />,
  );
  expect(screen.getByText(placeholder)).toBeInTheDocument();
});

test("an album card is square while a film card is portrait", () => {
  const { container: filmContainer } = render(<ResultCard result={film()} />);
  const { container: albumContainer } = render(
    <ResultCard result={film({ mediaType: "album", coverUrl: null })} />,
  );

  expect(filmContainer.querySelector(".aspect-\\[2\\/3\\]")).not.toBeNull();
  expect(albumContainer.querySelector(".aspect-square")).not.toBeNull();
});

test("a game card uses its own box shape, not the film poster's", () => {
  // TMDB posters are 342x513 (2:3); IGDB covers are 264x352 (3:4) — visibly stubbier, confirmed
  // by reading the real files. Sharing the film box left gray letterboxing top and bottom.
  const { container } = render(
    <ResultCard result={film({ mediaType: "game", coverUrl: null })} />,
  );

  expect(container.querySelector(".aspect-\\[3\\/4\\]")).not.toBeNull();
  expect(container.querySelector(".aspect-\\[2\\/3\\]")).toBeNull();
});

test("no type badge is shown by default", () => {
  render(<ResultCard result={film()} />);

  expect(screen.queryByText("Film")).not.toBeInTheDocument();
});

test("a type badge appears when asked for, labelled for the item's type", () => {
  render(<ResultCard result={film({ mediaType: "game" })} showBadge />);

  expect(screen.getByText("Game")).toBeInTheDocument();
});

test("titles are shown as text, never as HTML", () => {
  const hostileTitle = "<img src=x onerror=alert(1)>";
  render(<ResultCard result={film({ title: hostileTitle, coverUrl: null })} />);

  expect(screen.getByText(hostileTitle)).toBeInTheDocument();
  expect(document.querySelector("img[src='x']")).toBeNull();
});
