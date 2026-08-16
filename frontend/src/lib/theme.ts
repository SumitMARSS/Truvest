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

/** Perceived lightness of a bare `R G B` token value, 0 (black) to 1 (white). */
function tokenLightness(value: string): number | null {
  const parts = value.split(/[\s,/]+/).filter(Boolean).map(Number);
  if (parts.length < 3 || parts.some(Number.isNaN)) return null;
  const [r, g, b] = parts;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/**
 * Dev-time guard against the one failure mode that actually bit us: a browser
 * holding an older stylesheet (Tailwind config changes need a dev-server
 * restart, not just a reload) renders the app in a palette the running code
 * doesn't know about. The tokens are the contract — if they're absent, say so
 * loudly instead of leaving someone squinting at invisible text.
 *
 * Absent tokens are the easy case. The nastier one is a stylesheet that still
 * resolves tokens but disagrees with the active theme: `data-theme="dark"`
 * (so the pre-paint rule in index.html paints a dark page) while the
 * stylesheet hands back the LIGHT surface, producing a dark page wearing
 * light cards and near-black text. Both are reported here, because from the
 * reader's side they look identical: text they cannot see.
 */
export function warnIfThemeTokensMissing(): void {
  if (typeof document === "undefined") return;
  const surface = getComputedStyle(document.documentElement).getPropertyValue("--bg-surface").trim();
  if (!surface) {
    console.warn(
      "[Truvest] Theme tokens are missing — the page is running an outdated stylesheet. " +
        "Restart the dev server (npm run dev) or hard-reload to pick up the current CSS.",
    );
    return;
  }

  const lightness = tokenLightness(surface);
  if (lightness == null) return;
  const theme = readTheme();
  const stylesheetLooksLight = lightness > 0.5;
  if (stylesheetLooksLight !== (theme === "light")) {
    console.warn(
      `[Truvest] Theme mismatch — data-theme="${theme}" but the stylesheet resolves ` +
        `--bg-surface to a ${stylesheetLooksLight ? "light" : "dark"} value (${surface}). ` +
        "The page is running a stale CSS bundle, so parts of it will be unreadable. " +
        "Hard-reload (Ctrl+Shift+R), or restart the dev server if this persists.",
    );
  }
}
