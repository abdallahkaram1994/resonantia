import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Link from "./Link";

test("renders a real anchor with the href, so it works without JavaScript too", () => {
  render(<Link to="/item/5">The Title</Link>);

  const link = screen.getByRole("link", { name: "The Title" });
  expect(link).toHaveAttribute("href", "/item/5");
});

test("a plain click navigates without a full page load", () => {
  render(<Link to="/item/5">The Title</Link>);

  const notPrevented = fireEvent.click(screen.getByRole("link", { name: "The Title" }));

  expect(notPrevented).toBe(false); // our handler called preventDefault
  expect(window.location.pathname).toBe("/item/5");
});

test.each([
  ["a modifier key (open in a new tab)", { metaKey: true }],
  ["a middle click", { button: 1 }],
])("%s is left to the browser, not intercepted", (_name, options) => {
  render(<Link to="/item/5">The Title</Link>);

  const notPrevented = fireEvent.click(screen.getByRole("link", { name: "The Title" }), options);

  expect(notPrevented).toBe(true);
  expect(window.location.pathname).not.toBe("/item/5");
});
