import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { UnavailableNotice } from "@/components/Skeleton";
import type { ValuationContext } from "@/lib/api";

function fmtPe(n?: number | null) {
  return n == null ? "—" : n.toFixed(1);
}

/**
 * Valuation context is one of the two features that make this tool
 * "decision-relevant" rather than data-relevant (per spec), so it sits
 * directly under the header, above raw fundamentals — not buried below.
 */
export function ValuationPanel({
  valuation,
  currentPe,
}: {
  valuation: ValuationContext;
  currentPe?: number | null;
}) {
  const { pe_band, sector_pe } = valuation;

  return (
    <section className="rounded-xl border border-line bg-white/70 p-5">
      <h3 className="flex items-center gap-2 font-display text-lg font-semibold">
        Valuation context
        <ConfidenceBadge level={pe_band.available ? "high" : undefined} />
      </h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
            Historical P/E band {pe_band.partial_history && pe_band.available ? "(partial history)" : ""}
          </p>
          {pe_band.available ? (
            <div className="mt-2">
              <div className="flex items-baseline gap-2">
                <span className="font-display text-2xl font-bold">{fmtPe(currentPe)}</span>
                <span className="text-sm text-ink/55">current</span>
              </div>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-ink/10">
                {(() => {
                  const min = pe_band.band_min ?? 0;
                  const max = pe_band.band_max ?? 1;
                  const span = Math.max(max - min, 0.01);
                  const pos = currentPe != null ? Math.min(1, Math.max(0, (currentPe - min) / span)) : 0.5;
                  return (
                    <div className="relative h-full">
                      <div className="h-full w-full bg-gradient-to-r from-accent/30 via-warn/30 to-danger/30" />
                      <div
                        className="absolute top-0 h-2 w-1 -translate-x-1/2 bg-ink"
                        style={{ left: `${pos * 100}%` }}
                      />
                    </div>
                  );
                })()}
              </div>
              <div className="mt-1 flex justify-between text-xs text-ink/50">
                <span>{fmtPe(pe_band.band_min)} low</span>
                <span>{fmtPe(pe_band.band_avg)} avg</span>
                <span>{fmtPe(pe_band.band_max)} high</span>
              </div>
              <p className="mt-2 text-xs text-ink/45">
                From {pe_band.quarters_used} quarter(s) of price × EPS
                {pe_band.partial_history && " — fewer than 8 quarters available, band is directional only"}.
              </p>
            </div>
          ) : (
            <div className="mt-2">
              <UnavailableNotice reason={pe_band.reason} />
            </div>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Sector-average P/E</p>
          {sector_pe.available ? (
            <div className="mt-2">
              <div className="flex items-baseline gap-2">
                <span className="font-display text-2xl font-bold">{fmtPe(sector_pe.pe)}</span>
                <span className="text-sm text-ink/55">{sector_pe.sector}</span>
              </div>
              {currentPe != null && sector_pe.pe != null && (
                <p className="mt-1 text-sm text-ink/70">
                  Stock trades at {currentPe > sector_pe.pe ? "a premium to" : "a discount to"} its sector average.
                </p>
              )}
              <p className="mt-2 text-xs text-ink/45">
                As of {sector_pe.as_of} · {sector_pe.source === "static_fallback" ? "static fallback table (NSE pull unavailable)" : `NSE ${sector_pe.index}`}
              </p>
            </div>
          ) : (
            <div className="mt-2">
              <UnavailableNotice reason={sector_pe.reason} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
