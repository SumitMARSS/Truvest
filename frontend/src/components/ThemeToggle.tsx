import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";

/**
 * Dark/light switch. Small and quiet by design — it is a preference control,
 * not a feature to advertise.
 *
 * The initial value is read from `<html data-theme>`, which the bootstrap in
 * index.html has already set from localStorage; React never re-decides it, so
 * there is nothing to flash and nothing to reconcile.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => readTheme());

  // Cross-fade colours on change, then drop the class so ordinary hover and
  // focus transitions aren't slowed by a global transition rule.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("theme-transition");
    const id = setTimeout(() => root.classList.remove("theme-transition"), 220);
    return () => clearTimeout(id);
  }, [theme]);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  }

  const goingTo = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      role="switch"
      aria-checked={theme === "dark"}
      aria-label={`Switch to ${goingTo} theme`}
      title={`Switch to ${goingTo} theme`}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-surface text-muted transition hover:border-accent/40 hover:text-accent"
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
