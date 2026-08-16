/** @type {import('tailwindcss').Config} */

// Every colour resolves to a CSS variable defined in src/index.css, so the
// same utility class renders correctly in both themes and opacity modifiers
// (`text-ink/60`) still work. Token NAMES are unchanged from before the theme
// pass on purpose — the whole component tree re-themes without a rewrite.
// The fallback is the DARK value: if a variable is ever missing (a stale
// stylesheet, a partial load), utilities still resolve to a self-consistent
// dark palette instead of collapsing to transparent or mixing with an older
// light one.
const token = (name, fallback) => `rgb(var(${name}, ${fallback}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: token("--bg-primary", "9 13 21"), // page background
        surface: token("--bg-surface", "15 20 30"), // cards and panels
        elevated: token("--bg-elevated", "22 29 41"), // inner fills, hover, dropdown rows
        line: token("--border-primary", "33 43 58"), // hairline borders
        ink: token("--text-primary", "226 233 243"), // primary text
        secondary: token("--text-secondary", "183 194 210"), // supporting copy
        muted: token("--text-muted", "142 156 176"), // labels, captions, match reasons
        accent: token("--accent", "45 190 168"),
        success: token("--success", "62 196 138"),
        warn: token("--warn", "224 160 62"),
        danger: token("--danger", "235 108 100"),
        primary: token("--primary", "45 190 168"), // primary action surface
        onprimary: token("--on-primary", "6 18 18"), // text on the primary surface
      },
      fontFamily: {
        // One family at different weights: a research tool reads as serious
        // when the type system is quiet rather than decorative.
        display: ["var(--font-display)", "ui-sans-serif", "system-ui"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
      },
      boxShadow: {
        // Flat, close to the surface — no soft toy-like drop shadows.
        card: "0 1px 2px rgb(0 0 0 / 0.06), 0 1px 12px rgb(0 0 0 / 0.05)",
        pop: "0 10px 30px rgb(0 0 0 / 0.18)",
      },
    },
  },
  plugins: [],
};
