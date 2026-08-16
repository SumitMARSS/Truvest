import { FormEvent, useEffect, useState } from "react";
import { Loader2, Search, GitCompareArrows } from "lucide-react";
import { getResearch, startResearch, type ResearchJob } from "@/lib/api";
import { BriefView } from "@/components/BriefView";
import { CompareView } from "@/components/CompareView";
import { BriefSkeleton } from "@/components/BriefSkeleton";
import { PipelineStatus } from "@/components/PipelineStatus";
import { ErrorBoundary } from "@/components/ErrorBoundary";

const QUICK_PICKS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS", "ITC"];
const QUICK_COMPARES: Array<[string, string]> = [
  ["TCS", "INFY"],
  ["HDFCBANK", "ICICIBANK"],
  ["RELIANCE", "ONGC"],
];

const ERROR_MESSAGES: Record<string, string> = {
  ticker_not_found: "Couldn't resolve that to a live NSE/BSE symbol — try the exchange ticker (e.g. RELIANCE, TCS, INFY).",
  timeout: "This research job took too long and timed out. Try again — it's usually a transient slowdown upstream.",
  internal_error: "Something went wrong on our end while building this brief. Try again in a moment.",
};

export function ResearchStudio() {
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [query, setQuery] = useState("RELIANCE");
  const [queryA, setQueryA] = useState("TCS");
  const [queryB, setQueryB] = useState("INFY");
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function run(q: string) {
    setError(null);
    setSubmitting(true);
    setJob(null);
    try {
      const started = await startResearch(q.trim());
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

  return (
    <section className="space-y-8">
      <form
        onSubmit={onSubmit}
        className="rounded-2xl border border-line bg-white/60 p-5 shadow-sm md:p-6"
      >
        <div className="mb-4 inline-flex rounded-xl border border-line bg-paper/40 p-1 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setMode("single")}
            className={`rounded-lg px-3 py-1.5 transition ${mode === "single" ? "bg-ink text-paper" : "text-ink/60 hover:text-ink"}`}
          >
            <Search className="mr-1.5 inline h-3.5 w-3.5" />
            Single stock
          </button>
          <button
            type="button"
            onClick={() => setMode("compare")}
            className={`rounded-lg px-3 py-1.5 transition ${mode === "compare" ? "bg-ink text-paper" : "text-ink/60 hover:text-ink"}`}
          >
            <GitCompareArrows className="mr-1.5 inline h-3.5 w-3.5" />
            Compare two
          </button>
        </div>

        {mode === "single" ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1">
              <span className="mb-2 block text-sm font-semibold text-ink/70">
                NSE/BSE ticker or company
              </span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="RELIANCE / TCS / Infosys Ltd"
                className="w-full rounded-xl border border-line bg-white/80 px-4 py-3 text-lg outline-none ring-accent focus:ring-2"
                required
              />
            </label>
            <button
              type="submit"
              disabled={running}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ink px-6 py-3 font-semibold text-paper transition hover:bg-accent disabled:opacity-60"
            >
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {running ? "Researching…" : "Run research"}
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1">
              <span className="mb-2 block text-sm font-semibold text-ink/70">Stock A</span>
              <input
                value={queryA}
                onChange={(e) => setQueryA(e.target.value)}
                placeholder="TCS"
                className="w-full rounded-xl border border-line bg-white/80 px-4 py-3 text-lg outline-none ring-accent focus:ring-2"
                required
              />
            </label>
            <span className="pb-3 text-sm font-bold uppercase tracking-wide text-ink/40">vs</span>
            <label className="flex-1">
              <span className="mb-2 block text-sm font-semibold text-ink/70">Stock B</span>
              <input
                value={queryB}
                onChange={(e) => setQueryB(e.target.value)}
                placeholder="Infosys"
                className="w-full rounded-xl border border-line bg-white/80 px-4 py-3 text-lg outline-none ring-accent focus:ring-2"
                required
              />
            </label>
            <button
              type="submit"
              disabled={running}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ink px-6 py-3 font-semibold text-paper transition hover:bg-accent disabled:opacity-60"
            >
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitCompareArrows className="h-4 w-4" />}
              {running ? "Comparing…" : "Compare"}
            </button>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-ink/45">Try:</span>
          {mode === "single"
            ? QUICK_PICKS.map((t) => (
                <button
                  key={t}
                  type="button"
                  disabled={running}
                  onClick={() => {
                    setQuery(t);
                    void run(t);
                  }}
                  className="rounded-full border border-line bg-paper/50 px-3 py-1 text-sm font-medium text-ink/70 transition hover:border-accent hover:text-accent disabled:opacity-50"
                >
                  {t}
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
                    void run(`${a} vs ${b}`);
                  }}
                  className="rounded-full border border-line bg-paper/50 px-3 py-1 text-sm font-medium text-ink/70 transition hover:border-accent hover:text-accent disabled:opacity-50"
                >
                  {a} vs {b}
                </button>
              ))}
        </div>
      </form>

      {error && (
        <p className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-danger">{error}</p>
      )}
      {friendlyError && (
        <p className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-danger">{friendlyError}</p>
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
