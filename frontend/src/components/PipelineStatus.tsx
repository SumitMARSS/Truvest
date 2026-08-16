import { Check, Loader2 } from "lucide-react";
import type { ResearchJob } from "@/lib/api";

const STEPS = [
  { id: "resolve_ticker", label: "Resolve" },
  { id: "planner", label: "Plan" },
  { id: "market", label: "Market" },
  { id: "news", label: "News" },
  { id: "filings", label: "Filings" },
  { id: "peers", label: "Peers" },
  { id: "shareholding", label: "Holding" },
  { id: "calc", label: "Valuation" },
  { id: "synthesizer", label: "Synthesize" },
  { id: "critic", label: "Critic" },
  { id: "finalize", label: "Finalize" },
];

export function PipelineStatus({ job }: { job: ResearchJob }) {
  // Compare-mode progress is prefixed "a:"/"b:" per side (agents/runner.py) —
  // strip it for step-guessing; the label communicates it's a joint run.
  const rawProgress = (job.progress || "").toLowerCase();
  const progress = rawProgress.replace(/^[ab]:/, "");
  const activeIdx = guessStep(progress, job.status);

  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-card">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-base font-semibold tracking-tight">
          {job.mode === "compare" ? "Agent pipeline (both stocks)" : "Agent pipeline"}
        </h2>
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
          {job.status} · {job.progress || "—"}
        </span>
      </div>
      {/* Flex-wrap, not an 11-column grid: fixed columns squeezed the longest
          labels ("Synthesize") until they overflowed their own chip. */}
      <ol className="flex flex-wrap gap-1.5">
        {STEPS.map((step, i) => {
          const done = i < activeIdx || job.status === "completed";
          const active = i === activeIdx && job.status === "running";
          return (
            <li
              key={step.id}
              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] ${
                done
                  ? "border-accent/30 bg-accent/[0.07] text-accent"
                  : active
                    ? "border-warn/40 bg-warn/[0.07] text-warn"
                    : "border-line bg-elevated text-muted"
              }`}
            >
              {done ? (
                <Check className="h-3 w-3 shrink-0" />
              ) : active ? (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
              ) : null}
              {step.label}
            </li>
          );
        })}
      </ol>
      {job.error && <p className="mt-3 text-sm text-danger">{job.error}</p>}
    </div>
  );
}

function guessStep(progress: string, status: string): number {
  if (status === "completed") return STEPS.length;
  if (status === "pending") return 0;
  // market/news/filings/peers/shareholding run in PARALLEL — any *_done
  // message means that worker phase is underway; workers_joined means all
  // I/O workers finished.
  const map: Record<string, number> = {
    queued: 0,
    starting_agents: 1,
    planned: 1,
    planner_retry: 1,
    resolved: 0,
    market_done: 2,
    market_unavailable: 2,
    news_done: 3,
    filings_done: 4,
    peers_done: 5,
    shareholding_done: 6,
    workers_joined: 7,
    calc_done: 7,
    calc_skipped: 7,
    synthesized: 8,
    critic_pass: 9,
    critic_fail: 9,
    finalized: 10,
    done: 10,
  };
  for (const [k, v] of Object.entries(map)) {
    if (progress.includes(k)) return v;
  }
  return 1;
}
