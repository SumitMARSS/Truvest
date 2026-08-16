export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "truvest-theme";

/**
 * Theme state lives on `<html data-theme>`, written by the inline bootstrap in
 * index.html BEFORE first paint (so there is no light flash) and by this
 * module afterwards. React never owns the initial value — it reads what the
 * bootstrap already applied, which keeps the two in sync by construction.
 */
export function readTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Private mode / storage disabled — the theme still applies for this
    // session, it just won't be remembered.
  }
}

/**
 * Dev-time guard against the one failure mode that actually bit us: a browser
 * holding an older stylesheet (Tailwind config changes need a dev-server
 * restart, not just a reload) renders the app in a palette the running code
 * doesn't know about. The tokens are the contract — if they're absent, say so
 * loudly instead of leaving someone squinting at invisible text.
 */
export function warnIfThemeTokensMissing(): void {
  if (typeof document === "undefined") return;
  const surface = getComputedStyle(document.documentElement).getPropertyValue("--bg-surface").trim();
  if (!surface) {
    console.warn(
      "[Truvest] Theme tokens are missing — the page is running an outdated stylesheet. " +
        "Restart the dev server (npm run dev) or hard-reload to pick up the current CSS.",
    );
  }
}
