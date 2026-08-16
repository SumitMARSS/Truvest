import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { UnavailableNotice } from "@/components/Skeleton";
import type { PeerComparison, PeerRow } from "@/lib/api";

type SortKey = "ticker" | "last_price" | "change_1y_pct" | "pe_ratio" | "market_cap" | "yoy_revenue_growth";

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: "ticker", label: "Ticker" },
  { key: "last_price", label: "Price" },
  { key: "change_1y_pct", label: "1Y %" },
  { key: "pe_ratio", label: "P/E" },
  { key: "market_cap", label: "Mkt cap" },
  { key: "yoy_revenue_growth", label: "YoY rev" },
];

function fmtCompact(n?: number | null) {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function fmtPct(n?: number | null) {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

export function PeerTable({ comparison }: { comparison: PeerComparison }) {
  const [sortKey, setSortKey] = useState<SortKey>("market_cap");
  const [asc, setAsc] = useState(false);

  if (!comparison.available) {
    return <UnavailableNotice reason={comparison.reason} />;
  }

  const rows = [...comparison.rows].sort((a, b) => {
    const av = a[sortKey as keyof PeerRow];
    const bv = b[sortKey as keyof PeerRow];
    if (typeof av === "string" || typeof bv === "string") {
      return asc ? String(av ?? "").localeCompare(String(bv ?? "")) : String(bv ?? "").localeCompare(String(av ?? ""));
    }
    const an = (av as number) ?? -Infinity;
    const bn = (bv as number) ?? -Infinity;
    return asc ? an - bn : bn - an;
  });

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(false);
    }
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-elevated text-left text-xs uppercase tracking-wide text-muted">
            {COLUMNS.map((col) => (
              <th key={col.key} className="px-3 py-2 font-semibold">
                <button
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className="inline-flex items-center gap-1 hover:text-ink"
                >
                  {col.label}
                  <ArrowUpDown className="h-3 w-3" />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.ticker}
              className={
                r.is_subject
                  ? "border-b border-line bg-accent/10 font-semibold"
                  : "border-b border-line last:border-0 hover:bg-elevated"
              }
            >
              <td className="px-3 py-2">
                {r.is_subject && <span className="mr-1 text-accent">●</span>}
                {r.ticker.replace(/\.(NS|BO)$/, "")}
              </td>
              <td className="px-3 py-2">{r.last_price != null ? `₹${r.last_price.toFixed(2)}` : "—"}</td>
              <td className={`px-3 py-2 ${r.change_1y_pct != null && r.change_1y_pct < 0 ? "text-danger" : "text-accent"}`}>
                {fmtPct(r.change_1y_pct)}
              </td>
              <td className="px-3 py-2">{r.pe_ratio != null ? r.pe_ratio.toFixed(1) : "—"}</td>
              <td className="px-3 py-2">{fmtCompact(r.market_cap)}</td>
              <td className="px-3 py-2">{fmtPct(r.yoy_revenue_growth)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
