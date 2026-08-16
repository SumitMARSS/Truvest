import { useEffect, useState } from "react";
import { ResearchStudio } from "@/components/ResearchStudio";
import { BrandMark } from "@/components/BrandMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getHealth } from "@/lib/api";

/**
 * Shared page container. Wide enough for the peer/compare tables to breathe on
 * a desktop monitor, capped so line lengths stay readable, and padded more
 * generously as the viewport grows.
 */
const CONTAINER = "mx-auto w-full max-w-[1440px] px-4 sm:px-6 lg:px-8";

const COVERAGE = [
  "Price action",
  "Fundamentals",
  "Valuation",
  "Promoter holding",
  "Peers",
  "News",
  "Risks",
];

export default function App() {
  // Provider, not model: the model is now the user's per-run choice and lives
  // in the picker inside the form. A second model label up here would go stale
  // the moment they change it and read as a contradiction.
  const [provider, setProvider] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then((h) => {
      if (h?.llm_provider) setProvider(h.llm_provider);
    });
  }, []);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-paper/90 backdrop-blur">
        <div className={`${CONTAINER} flex items-center justify-between gap-3 py-3`}>
          <div className="flex min-w-0 items-center gap-2.5">
            <BrandMark className="h-7 w-7 shrink-0" />
            <span className="font-display text-lg font-bold tracking-tight text-ink">Truvest</span>
            <span className="hidden rounded border border-line px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink/70 md:inline">
              Equity research agents
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
            <span className="hidden items-center gap-1.5 sm:inline-flex">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
              NSE / BSE
            </span>
            {provider && (
              <span
                className="hidden rounded border border-line bg-surface px-2 py-1 font-medium text-muted lg:inline"
                title="LLM provider this server is configured against"
              >
                {provider}
              </span>
            )}
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className={`${CONTAINER} pb-16 pt-8 md:pt-12`}>
        <section className="mb-7 max-w-3xl">
          <h1 className="font-display text-[1.9rem] font-bold leading-[1.15] tracking-tight text-ink sm:text-[2.25rem]">
            Sourced equity research,
            <br className="hidden sm:block" /> run by agents.
          </h1>
          <p className="mt-3 text-base leading-relaxed text-muted">
            Planner → workers → critic for <span className="font-semibold text-ink/85">Indian equities</span>. Every
            claim is linked to its source and tagged with a confidence level.
          </p>
          <ul className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs text-ink/70">
            {COVERAGE.map((item, i) => (
              <li key={item} className="flex items-center gap-2">
                {i > 0 && <span className="text-muted" aria-hidden="true">·</span>}
                {item}
              </li>
            ))}
          </ul>
        </section>

        <ResearchStudio />

        <footer className="mt-14 rounded-xl border border-line bg-surface/60 p-5">
          <div className="flex items-center gap-2">
            <BrandMark className="h-5 w-5" />
            <span className="font-display text-sm font-bold tracking-tight text-ink/80">Truvest</span>
          </div>
          <div className="mt-3 grid gap-x-8 gap-y-2 text-[13px] leading-relaxed text-muted sm:grid-cols-2">
            <p>
              AI-generated research from public market data — Yahoo Finance, NSE disclosures, Indian financial-press
              RSS and Tavily search.
            </p>
            <p>
              <span className="font-semibold text-ink/70">Not investment advice.</span> Every claim is source-linked
              and confidence-tagged; unavailable data is shown as unavailable, never estimated.
            </p>
          </div>
        </footer>
      </main>
    </div>
  );
}
