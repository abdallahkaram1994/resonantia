import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Era, MediaType } from "./api";
import SearchFilters, { DEFAULT_TYPES } from "./SearchFilters";

function setup(types: MediaType[] = ["film", "game", "album"], eras: Era[] = []) {
  const onTypesChange = vi.fn();
  const onErasChange = vi.fn();
  render(
    <SearchFilters
      types={types}
      eras={eras}
      onTypesChange={onTypesChange}
      onErasChange={onErasChange}
    />,
  );
  return { onTypesChange, onErasChange };
}

test("every type is checked when given, regardless of what the app treats as default", () => {
  setup();

  expect(screen.getByRole("checkbox", { name: "Films" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Games" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Albums" })).toBeChecked();
});

test("the app's default types are films and games, not albums", () => {
  // Albums are left out of the default: a small number of them sit disproportionately close to
  // many unrelated queries in the shared embedding space ("hubness"), confirmed on the real
  // catalog. Still fully searchable by checking the box back on.
  expect(DEFAULT_TYPES).toEqual(["film", "game"]);
});

test("with the default types, only films and games are checked", () => {
  setup(DEFAULT_TYPES);

  expect(screen.getByRole("checkbox", { name: "Films" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Games" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Albums" })).not.toBeChecked();
});

test("unchecking a type reports the remaining ones", () => {
  const { onTypesChange } = setup();

  screen.getByRole("checkbox", { name: "Games" }).click();

  expect(onTypesChange).toHaveBeenCalledWith(["film", "album"]);
});

test("checking a type back reports it restored in catalog order", () => {
  const { onTypesChange } = setup(["film", "album"]);

  screen.getByRole("checkbox", { name: "Games" }).click();

  expect(onTypesChange).toHaveBeenCalledWith(["film", "game", "album"]);
});

test("the last remaining type cannot be unchecked", () => {
  const { onTypesChange } = setup(["game"]);

  const checkbox = screen.getByRole("checkbox", { name: "Games" });
  expect(checkbox).toBeDisabled();
  checkbox.click();

  expect(onTypesChange).not.toHaveBeenCalled();
});

test("the toggle handler itself refuses to drop the last type, not only the disabled checkbox", () => {
  const { onTypesChange } = setup(["game"]);

  // The checkbox is also disabled (checked above), which already stops a real click; bypass it
  // to prove the handler enforces the same rule on its own, not only through that attribute.
  const checkbox = screen.getByRole("checkbox", { name: "Games" }) as HTMLInputElement;
  checkbox.disabled = false;
  fireEvent.click(checkbox);

  expect(onTypesChange).not.toHaveBeenCalled();
});

test("no decade is pressed by default", () => {
  setup();

  expect(screen.getByRole("button", { name: "80s" })).toHaveAttribute("aria-pressed", "false");
});

test("clicking a decade reports it added", () => {
  const { onErasChange } = setup();

  screen.getByRole("button", { name: "80s" }).click();

  expect(onErasChange).toHaveBeenCalledWith([{ start: 1980, end: 1989 }]);
});

test("clicking a pressed decade reports it removed", () => {
  const { onErasChange } = setup(["film", "game", "album"], [{ start: 1980, end: 1989 }]);

  const button = screen.getByRole("button", { name: "80s" });
  expect(button).toHaveAttribute("aria-pressed", "true");
  button.click();

  expect(onErasChange).toHaveBeenCalledWith([]);
});

test("several decades can be pressed at once, each reported independently", () => {
  const { onErasChange } = setup(["film", "game", "album"], [{ start: 1980, end: 1989 }]);

  screen.getByRole("button", { name: "90s" }).click();

  expect(onErasChange).toHaveBeenCalledWith([
    { start: 1980, end: 1989 },
    { start: 1990, end: 1999 },
  ]);
});
