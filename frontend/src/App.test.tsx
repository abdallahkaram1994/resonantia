import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("the page has the product name, the search box and the TMDB attribution", () => {
  render(<App />);

  expect(screen.getByRole("heading", { level: 1, name: "Resonantia" })).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toHaveTextContent(/not endorsed or certified by TMDB/);
});
