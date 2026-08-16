import { TrendIndicator } from "@/components/TrendIndicator";
import { BriefView } from "@/components/BriefView";
import type { CompareBrief } from "@/lib/api";

function fmtMoney(n?: number | null, currency = "INR") {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency || "INR",
    notation: Math.abs(n) >= 1e7 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(n);
}

/** Dedicated compare-mode rendering (spec 2.7) — a metrics table + narrative
 * up top, with each side's full individual brief available below for anyone
 * who wants to dig into citations/confidence for a specific stock. */
export function CompareView({ compare }: { compare: CompareBrief }) {
  const [rowA, rowB] = compare.metrics_table as Array<Record<string, any>>;

  return (
    <div className="space-y-8">
      <article className="rounded-2xl border border-line bg-white/60 p-6 shadow-sm md:p-8">
        <header className="border-b border-line pb-6">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-accent">Comparison</p>
          <h2 className="mt-2 font-display text-3xl font-bold">
            {compare.tickers.map((t) => t.replace(/\.(NS|BO)$/, "")).join(" vs ")}
          </h2>
          <p className="mt-1 text-sm text-ink/55">As of {new Date(compare.as_of).toLocaleString()}</p>
        </header>

        <p className="mt-6 rounded-xl border border-line bg-paper/50 px-4 py-3 text-sm text-ink/60">
          <span className="font-semibold text-ink/75">Not investment advice.</span> Side-by-side data
          comparison only — no price targets or buy/sell calls.
        </p>

        <section className="mt-6">
          <h3 className="font-display text-xl font-semibold">Comparison summary</h3>
          <p className="mt-3 leading-relaxed text-ink/85">{compare.comparison_summary}</p>
        </section>

        {rowA && rowB && (
          <section className="mt-6 overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[480px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-paper/50 text-left text-xs uppercase tracking-wide text-ink/50">
                  <th className="px-3 py-2">Metric</th>
                  <th className="px-3 py-2">{String(rowA.ticker).replace(/\.(NS|BO)$/, "")}</th>
                  <th className="px-3 py-2">{String(rowB.ticker).replace(/\.(NS|BO)$/, "")}</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">Last price</td>
                  <td className="px-3 py-2 font-semibold">{fmtMoney(rowA.last_price, rowA.currency)}</td>
                  <td className="px-3 py-2 font-semibold">{fmtMoney(rowB.last_price, rowB.currency)}</td>
                </tr>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">1Y change</td>
                  <td className="px-3 py-2">
                    <TrendIndicator value={rowA.change_1y_pct} decimals={1} />
                  </td>
                  <td className="px-3 py-2">
                    <TrendIndicator value={rowB.change_1y_pct} decimals={1} />
                  </td>
                </tr>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">P/E ratio</td>
                  <td className="px-3 py-2 font-semibold">{rowA.pe_ratio?.toFixed(1) ?? "—"}</td>
                  <td className="px-3 py-2 font-semibold">{rowB.pe_ratio?.toFixed(1) ?? "—"}</td>
                </tr>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">Sector avg P/E</td>
                  <td className="px-3 py-2">{rowA.sector_pe?.toFixed?.(1) ?? "—"}</td>
                  <td className="px-3 py-2">{rowB.sector_pe?.toFixed?.(1) ?? "—"}</td>
                </tr>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">YoY revenue growth</td>
                  <td className="px-3 py-2">
                    <TrendIndicator value={rowA.yoy_revenue_growth} decimals={1} />
                  </td>
                  <td className="px-3 py-2">
                    <TrendIndicator value={rowB.yoy_revenue_growth} decimals={1} />
                  </td>
                </tr>
                <tr className="border-b border-line">
                  <td className="px-3 py-2 text-ink/55">Promoter holding</td>
                  <td className="px-3 py-2">{rowA.promoter_pct != null ? `${rowA.promoter_pct}%` : "—"}</td>
                  <td className="px-3 py-2">{rowB.promoter_pct != null ? `${rowB.promoter_pct}%` : "—"}</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 text-ink/55">News sentiment</td>
                  <td className="px-3 py-2 capitalize">{String(rowA.overall_news_sentiment || "—").replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 capitalize">{String(rowB.overall_news_sentiment || "—").replace(/_/g, " ")}</td>
                </tr>
              </tbody>
            </table>
          </section>
        )}
      </article>

      {/* min-w-0 on each grid item is load-bearing: grid items default to
          min-width:auto, so without it the peer table's min-w-[560px] forces
          the column wider than the viewport and the whole PAGE scrolls
          sideways on mobile instead of just the table scrolling in place. */}
      <div className="grid gap-6 lg:grid-cols-2">
        {compare.briefs.map((b) => (
          <div key={b.ticker} className="min-w-0">
            <BriefView brief={b} />
          </div>
        ))}
      </div>
    </div>
  );
}
