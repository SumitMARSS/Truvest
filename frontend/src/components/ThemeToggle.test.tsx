import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "./ThemeToggle";
import { THEME_STORAGE_KEY, readTheme } from "@/lib/theme";

/**
 * The theme contract, not the pixels: dark is the default, the choice is
 * remembered, and `<html data-theme>` is the single source of truth that the
 * CSS variables key off.
 */
beforeEach(() => {
  localStorage.clear();
  // index.html's bootstrap sets this before React mounts; reproduce that.
  document.documentElement.dataset.theme = "dark";
});

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("ThemeToggle", () => {
  it("starts from the theme the page bootstrap applied", () => {
    render(<ThemeToggle />);
    const toggle = screen.getByRole("switch");
    expect(toggle).toBeChecked(); // aria-checked = dark
    expect(toggle).toHaveAccessibleName(/switch to light theme/i);
  });

  it("switches to light and back, writing the html attribute each time", () => {
    render(<ThemeToggle />);
    const toggle = screen.getByRole("switch");

    fireEvent.click(toggle);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(readTheme()).toBe("light");
    expect(toggle).toHaveAccessibleName(/switch to dark theme/i);

    fireEvent.click(toggle);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(readTheme()).toBe("dark");
  });

  it("persists the choice so a refresh restores it", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("switch"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("survives storage being unavailable", () => {
    const getItem = Storage.prototype.getItem;
    const setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("storage disabled");
    };
    try {
      render(<ThemeToggle />);
      fireEvent.click(screen.getByRole("switch"));
      // The theme still applies for this session even though it can't be saved.
      expect(document.documentElement.dataset.theme).toBe("light");
    } finally {
      Storage.prototype.setItem = setItem;
      Storage.prototype.getItem = getItem;
    }
  });
});
