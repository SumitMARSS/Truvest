import { FormEvent, useEffect, useState } from "react";
import { Loader2, Search, GitCompareArrows, Lightbulb } from "lucide-react";
import {
  getResearch,
  listModels,
  startResearch,
  type ModelCatalog,
  type ResearchJob,
  type StockSuggestion,
} from "@/lib/api";
import { BriefView } from "@/components/BriefView";
import { CompareView } from "@/components/CompareView";
import { BriefSkeleton } from "@/components/BriefSkeleton";
import { ModelPicker } from "@/components/ModelPicker";
import { PipelineStatus } from "@/components/PipelineStatus";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { StockSearchInput } from "@/components/StockSearchInput";

/**
 * Example queries, not shortcuts. Clicking one fills the box and shows the
 * ranked matches — it deliberately does NOT start a research job, because a
 * job takes minutes and should always be something the user chose explicitly.
 * The set doubles as a demo of what the search accepts: a symbol, a company
 * name, a partial, a brand, a sector, an approximate spelling.
 */
const EXAMPLE_QUERIES: Array<{ text: string; note: string }> = [
  { text: "RELIANCE", note: "symbol" },
  { text: "Infosys", note: "company" },
  { text: "hdfc", note: "partial" },
  { text: "maggi", note: "brand" },
  { text: "pharma stocks", note: "sector" },
  { text: "tata motor", note: "close enough" },
];

const QUICK_COMPARES: Array<[string, string]> = [
  ["TCS", "INFY"],
  ["HDFCBANK", "ICICIBANK"],
  ["RELIANCE", "ONGC"],
];

const ERROR_MESSAGES: Record<string, string> = {
  ticker_not_found: "Couldn't resolve that to a live NSE/BSE symbol — try the exchange ticker (e.g. RELIANCE, TCS, INFY).",
  data_provider_unavailable:
    "Our market data provider is refusing requests right now, so this ticker couldn't be confirmed. Nothing's wrong with what you typed — try again shortly.",
  timeout: "This research job took too long and timed out. Try again — it's usually a transient slowdown upstream.",
  internal_error: "Something went wrong on our end while building this brief. Try again in a moment.",
};

const ACTION_BUTTON =
  "inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-onprimary transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50";

// The model choice survives reloads — it's a working preference, and re-picking
// it on every visit would be tedious. null (absent) means "server default", so
// the app keeps following the default if the server's changes.
const MODEL_STORAGE_KEY = "truvest:model";

function readStoredModel(): string | null {
  try {
    return localStorage.getItem(MODEL_STORAGE_KEY);
  } catch {
    // Private mode / blocked storage — a preference is not worth an exception.
    return null;
  }
}

function storeModel(modelId: string | null) {
  try {
    if (modelId) localStorage.setItem(MODEL_STORAGE_KEY, modelId);
    else localStorage.removeItem(MODEL_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function ResearchStudio() {
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [query, setQuery] = useState("RELIANCE");
  const [queryA, setQueryA] = useState("TCS");
  const [queryB, setQueryB] = useState("INFY");
  // Bumped to ask the search box to look up its current value and show
  // matches (the "Try searching" examples). Compare mode has no equivalent:
  // its examples fill both fields, and the user presses Compare.
  const [openSingle, setOpenSingle] = useState(0);
  // Set when the single-stock box contains "A vs B" — offer compare instead of
  // silently running a comparison the user didn't switch modes for.
  const [comparePair, setComparePair] = useState<[string, string] | null>(null);
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // null = run on whatever the server says its default is.
  const [model, setModel] = useState<string | null>(() => readStoredModel());
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);

  useEffect(() => {
    let cancelled = false;
    listModels().then((next) => {
      if (cancelled || !next) return;
      setCatalog(next);
      // A stored pick can outlive the model itself — free models get retired.
      // Drop it rather than sending an id the backend will reject with a 400.
      setModel((current) => {
        if (!current || next.models.some((m) => m.id === current)) return current;
        storeModel(null);
        return null;
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function chooseModel(next: string | null) {
    setModel(next);
    storeModel(next);
  }

  async function run(q: string) {
    setError(null);
    setSubmitting(true);
    setJob(null);
    setComparePair(null);
    try {
      const started = await startResearch(q.trim(), model);
      setJob(started);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (mode === "compare") void run(`${queryA} vs ${queryB}`);
    else void run(query);
  }

  function tryExample(text: string) {
    setQuery(text);
    setOpenSingle((n) => n + 1);
  }

  function switchToCompare([a, b]: [string, string]) {
    setQueryA(a);
    setQueryB(b);
    setMode("compare");
    setComparePair(null);
  }

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;

    // Hosted LLM + parallel workers → jobs finish in seconds; poll snappily
    const POLL_MS = 2000;
    const MAX_POLL_MS = 10 * 60 * 1000;
    const startedAt = Date.now();
    let inFlight = false;

    const id = setInterval(async () => {
      if (inFlight) return; // don't stack requests if the server is busy
      if (Date.now() - startedAt > MAX_POLL_MS) {
        clearInterval(id);
        setError("Stopped polling after 10 minutes — the research job is taking too long.");
        return;
      }
      inFlight = true;
      try {
        const next = await getResearch(job.job_id);
        setJob(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Poll failed");
      } finally {
        inFlight = false;
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [job?.job_id, job?.status]);

  const running = submitting || job?.status === "pending" || job?.status === "running";
  const friendlyError =
    job?.status === "failed" ? ERROR_MESSAGES[job.error_code || ""] || job.error : null;
  // A failed resolution ships its own ranked alternatives — one click recovers.
  const didYouMean: StockSuggestion[] =
    job?.status === "failed" && job.error_code === "ticker_not_found" ? job.suggestions || [] : [];

  const segment = (active: boolean) =>
    `inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-semibold transition ${
      active ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
    }`;

  const chip =
    "rounded-lg border border-line bg-elevated px-2.5 py-1.5 text-sm text-ink/75 transition hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <section className="space-y-6">
      <form
        onSubmit={onSubmit}
        className="rounded-xl border border-line bg-surface p-4 shadow-card sm:p-5 md:p-6"
      >
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div
            className="inline-flex rounded-lg border border-line bg-elevated p-1"
            role="group"
            aria-label="Search mode"
          >
            <button
              type="button"
              onClick={() => setMode("single")}
              aria-pressed={mode === "single"}
              className={segment(mode === "single")}
            >
              <Search className="h-3.5 w-3.5" />
              Single stock
            </button>
            <button
              type="button"
              onClick={() => setMode("compare")}
              aria-pressed={mode === "compare"}
              className={segment(mode === "compare")}
            >
              <GitCompareArrows className="h-3.5 w-3.5" />
              Compare two
            </button>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-muted xl:inline">
              Ticker · company · brand · sector · plain English
            </span>
            <ModelPicker
              catalog={catalog}
              value={model}
              onChange={chooseModel}
              disabled={running}
            />
          </div>
        </div>

        {/* Stable keys per mode: without them React reconciles the single and
            compare boxes as the same element, so switching tabs inherits the
            previous box's matches and shows a list nobody opened. */}
        {mode === "single" ? (
          <StockSearchInput
            key="single"
            label="Search a listed company"
            value={query}
            onChange={setQuery}
            onSelect={(choice) => void run(choice.symbol)}
            onComparePair={setComparePair}
            placeholder="RELIANCE / Infosys / maggi / pharma stocks"
            hint="Matches are ranked with a confidence score — pick one, or run your text as typed."
            disabled={running}
            openSignal={openSingle}
            action={
              <button type="submit" disabled={running} className={ACTION_BUTTON}>
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {running ? "Researching…" : "Run research"}
              </button>
            }
          />
        ) : (
          <div className="space-y-4">
            {/* Each field owns the vertical space its own matches take, so one
                list opening can never displace or cover the other field. */}
            <div className="grid gap-4 sm:grid-cols-2">
              <StockSearchInput
                key="compare-a"
                label="Stock A"
                value={queryA}
                onChange={setQueryA}
                onSelect={(choice) => setQueryA(choice.symbol)}
                selectHint="Click a match to set Stock A"
                placeholder="TCS"
                disabled={running}
              />
              <StockSearchInput
                key="compare-b"
                label="Stock B"
                value={queryB}
                onChange={setQueryB}
                onSelect={(choice) => setQueryB(choice.symbol)}
                selectHint="Click a match to set Stock B"
                placeholder="Infosys"
                disabled={running}
              />
            </div>
            <div className="flex justify-end">
              <button type="submit" disabled={running} className={`${ACTION_BUTTON} w-full sm:w-auto`}>
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitCompareArrows className="h-4 w-4" />}
                {running ? "Comparing…" : "Compare both"}
              </button>
            </div>
          </div>
        )}

        {mode === "single" && comparePair && !running && (
          <button
            type="button"
            onClick={() => switchToCompare(comparePair)}
            className="mt-3 inline-flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/[0.07] px-3 py-2 text-sm font-medium text-accent transition hover:bg-accent/[0.12]"
          >
            <GitCompareArrows className="h-3.5 w-3.5" />
            That reads as a comparison — switch to compare {comparePair[0]} vs {comparePair[1]}
          </button>
        )}

        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
            {mode === "single" ? "Try searching" : "Try a comparison"}
          </p>
          <div className="flex flex-wrap gap-2">
            {mode === "single"
              ? EXAMPLE_QUERIES.map((example) => (
                  <button
                    key={example.text}
                    type="button"
                    disabled={running}
                    title={`Fills the search box and shows ranked matches (${example.note})`}
                    onClick={() => tryExample(example.text)}
                    className={`group ${chip}`}
                  >
                    {example.text}
                    <span className="ml-1.5 text-[11px] text-muted group-hover:text-accent/70">
                      {example.note}
                    </span>
                  </button>
                ))
              : QUICK_COMPARES.map(([a, b]) => (
                  <button
                    key={`${a}-${b}`}
                    type="button"
                    disabled={running}
                    onClick={() => {
                      setQueryA(a);
                      setQueryB(b);
                    }}
                    className={chip}
                  >
                    {a} <span className="text-muted">vs</span> {b}
                  </button>
                ))}
          </div>
        </div>
      </form>

      {error && (
        <p className="rounded-xl border border-danger/30 bg-danger/[0.06] px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}
      {friendlyError && (
        <div className="rounded-xl border border-danger/30 bg-danger/[0.06] px-4 py-3 text-sm text-danger">
          <p>{friendlyError}</p>
          {didYouMean.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
                <Lightbulb className="h-3.5 w-3.5" />
                Did you mean
              </span>
              {didYouMean.map((s) => (
                <button
                  key={s.ticker}
                  type="button"
                  disabled={running}
                  title={`${s.name} — ${s.match_reason} (${Math.round(s.score * 100)}% match)`}
                  onClick={() => {
                    setQuery(s.symbol);
                    void run(s.symbol);
                  }}
                  className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm font-medium text-ink/75 transition hover:border-accent/50 hover:text-accent disabled:opacity-50"
                >
                  {s.symbol}
                  <span className="ml-1.5 text-[11px] text-muted">{Math.round(s.score * 100)}%</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {job && job.status !== "failed" && <PipelineStatus job={job} />}
      {running && !job?.brief && !job?.compare_brief && <BriefSkeleton />}

      <ErrorBoundary>
        {job?.mode === "compare" && job.compare_brief && <CompareView compare={job.compare_brief} />}
        {job?.mode !== "compare" && job?.brief && <BriefView brief={job.brief} />}
      </ErrorBoundary>
    </section>
  );
}
