import { AlertTriangle } from "lucide-react";

/** Surfaces every honest degradation from the brief in one visible place —
 * never a silent gap (spec: "every new external data call must degrade
 * gracefully and say so in the UI"). */
export function DataGapBanner({ gaps }: { gaps: string[] }) {
  if (!gaps?.length) return null;
  return (
    <div className="rounded-xl border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
      <p className="mb-1 flex items-center gap-1.5 font-semibold">
        <AlertTriangle className="h-4 w-4" />
        {gaps.length} section{gaps.length > 1 ? "s" : ""} degraded gracefully this run
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-warn/90">
        {gaps.map((g, i) => (
          <li key={`${i}-${g.slice(0, 30)}`}>{g}</li>
        ))}
      </ul>
    </div>
  );
}
