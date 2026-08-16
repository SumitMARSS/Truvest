import { TrendIndicator } from "@/components/TrendIndicator";
import { UnavailableNotice } from "@/components/Skeleton";
import type { Shareholding } from "@/lib/api";

/** A falling promoter stake is the single highest-signal number in this
 * section (per spec) — the QoQ delta gets a glanceable trend arrow, not
 * just a raw number next to another raw number. */
export function ShareholdingCard({ shareholding }: { shareholding: Shareholding }) {
  if (!shareholding.available) {
    return <UnavailableNotice reason={shareholding.reason} />;
  }

  const delta = shareholding.promoter_qoq_delta;
  const flagged = delta != null && delta < 0;

  return (
    <div className={`rounded-xl border p-4 ${flagged ? "border-danger/30 bg-danger/5" : "border-line bg-elevated"}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">Promoter holding</p>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="font-display text-3xl font-bold">{shareholding.promoter_pct}%</span>
        <TrendIndicator value={delta} suffix=" pts QoQ" decimals={2} />
      </div>
      <p className="mt-2 text-xs text-muted">
        As of {shareholding.as_of}
        {shareholding.prior_quarter_date && ` · prior quarter ${shareholding.prior_quarter_date}`}
      </p>
      {flagged && (
        <p className="mt-2 text-sm font-medium text-danger">
          Promoter stake declined quarter-over-quarter — worth independent verification.
        </p>
      )}
    </div>
  );
}
