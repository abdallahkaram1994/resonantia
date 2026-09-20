import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Footer from "./Footer";

test("attributes TMDB with the required non-endorsement notice", () => {
  render(<Footer />);

  expect(
    screen.getByText("This product uses the TMDB API but is not endorsed or certified by TMDB."),
  ).toBeInTheDocument();
  expect(screen.getByText(/Film data and posters come from TMDB/)).toBeInTheDocument();
});

test("shows the official TMDB logo, unmodified, linking to TMDB", () => {
  render(<Footer />);

  const logo = screen.getByRole("img", { name: "TMDB" });
  expect(logo.getAttribute("src")).toMatch(
    /^https:\/\/www\.themoviedb\.org\/assets\/v4\/logos\/v2\/blue_short-[0-9a-f]+\.svg$/,
  );
  expect(logo).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(logo).not.toHaveAttribute("width");
  const link = screen.getByRole("link", { name: "TMDB" });
  expect(link).toHaveAttribute("href", "https://www.themoviedb.org/");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
});
