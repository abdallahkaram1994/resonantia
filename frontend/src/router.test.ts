import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { navigate, useLocation } from "./router";

test("reports the current path and query string", () => {
  window.history.replaceState(null, "", "/search?q=rain");

  const { result } = renderHook(() => useLocation());

  expect(result.current).toBe("/search?q=rain");
});

test("navigate pushes a new url and every subscriber sees it", () => {
  const { result } = renderHook(() => useLocation());

  act(() => navigate("/item/5"));

  expect(result.current).toBe("/item/5");
  expect(window.location.pathname).toBe("/item/5");
});

test("a real back/forward navigation (popstate) is picked up too", () => {
  const { result } = renderHook(() => useLocation());

  act(() => {
    window.history.replaceState(null, "", "/search?q=two");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  expect(result.current).toBe("/search?q=two");
});
