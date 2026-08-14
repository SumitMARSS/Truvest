import { Check, Loader2 } from "lucide-react";
import type { ResearchJob } from "@/lib/api";

const STEPS = [
  { id: "resolve_ticker", label: "Resolve" },
  { id: "planner", label: "Plan" },
  { id: "market", label: "Market" },
  { id: "news", label: "News" },
  { id: "filings", label: "Filings" },
  { id: "calc", label: "Calc" },
  { id: "synthesizer", label: "Synthesize" },
  { id: "critic", label: "Critic" },
  { id: "finalize", label: "Finalize" },
];

export function PipelineStatus({ job }: { job: ResearchJob }) {
  const progress = (job.progress || "").toLowerCase();
  const activeIdx = guessStep(progress, job.status);

  return (
    <div className="rounded-2xl border border-line bg-white/50 p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-xl font-semibold">Agent pipeline</h2>
        <span className="text-sm uppercase tracking-wide text-ink/60">
          {job.status} · {job.progress || "—"}
        </span>
      </div>
      <ol className="grid gap-2 sm:grid-cols-3 md:grid-cols-5 lg:grid-cols-9">
        {STEPS.map((step, i) => {
          const done = i < activeIdx || job.status === "completed";
          const active = i === activeIdx && job.status === "running";
          return (
            <li
              key={step.id}
              className={`flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-center text-xs font-semibold uppercase tracking-wide ${
                done
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : active
                    ? "border-warn/50 bg-warn/10 text-warn"
                    : "border-line text-ink/40"
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
  // market/news/filings run in PARALLEL — any *_done message means the worker
  // phase is underway; workers_joined means all I/O workers finished
  const map: Record<string, number> = {
    queued: 0,
    starting_agents: 1,
    planned: 1,
    planner_retry: 1,
    resolved: 0,
    market_done: 2,
    news_done: 3,
    filings_done: 4,
    workers_joined: 5,
    calc_done: 5,
    calc_skipped: 5,
    synthesized: 6,
    critic_pass: 7,
    critic_fail: 7,
    finalized: 8,
    done: 8,
  };
  for (const [k, v] of Object.entries(map)) {
    if (progress.includes(k)) return v;
  }
  return 1;
}
