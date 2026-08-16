/**
 * Every async section gets its own skeleton instead of one blocking spinner
 * for the whole brief (docs/AUDIT.md #6.2) — progressive reveal reads as a
 * live system working, not a stalled page.
 */
export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-ink/8 ${className}`} />;
}

export function SkeletonCard({ title, lines = 3 }: { title: string; lines?: number }) {
  return (
    <div className="rounded-xl border border-line bg-elevated p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <SkeletonBlock key={i} className={`h-3 ${i === lines - 1 ? "w-2/3" : "w-full"}`} />
        ))}
      </div>
    </div>
  );
}

/** Honest, explicit "this isn't available" state — never a silent blank gap. */
export function UnavailableNotice({ reason }: { reason?: string | null }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-elevated p-4 text-sm text-muted">
      <span className="font-semibold text-ink/70">Unavailable this cycle. </span>
      {reason || "This data source did not respond — never fabricated to fill the gap."}
    </div>
  );
}
