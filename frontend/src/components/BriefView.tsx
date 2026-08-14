import { useState } from "react";
import type { ResearchBrief, SourceRef } from "@/lib/api";

function fmtMoney(n?: number | null, currency = "INR") {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: currency || "INR",
    notation: Math.abs(n) >= 1e7 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(n);
}

function fmtPct(n?: number | null) {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function pctTone(n?: number | null) {
  if (n == null) return "text-ink/50";
  return n >= 0 ? "text-accent" : "text-danger";
}

function Cite({ ids, sources }: { ids: string[]; sources: SourceRef[] }) {
  if (!ids?.length) return null;
  return (
    <span className="ml-1 text-[11px] text-accent">
      {ids.map((id) => {
        const s = sources.find((x) => x.id === id);
        const label = id.replace(/^src-/, "");
        return s?.url ? (
          <a key={id} href={s.url} target="_blank" rel="noreferrer" className="mr-1 underline">
            [{label}]
          </a>
        ) : (
          <span key={id} className="mr-1">
            [{label}]
          </span>
        );
      })}
    </span>
  );
}

const PERF_PERIODS = [
  { key: "1W", label: "1 week", field: "change_1w_pct", days: 7 },
  { key: "1M", label: "1 month", field: "change_1m_pct", days: 30 },
  { key: "3M", label: "3 months", field: "change_3m_pct", days: 91 },
  { key: "6M", label: "6 months", field: "change_6m_pct", days: 182 },
  { key: "1Y", label: "1 year", field: "change_1y_pct", days: 365 },
  { key: "3Y", label: "3 years", field: "change_3y_pct", days: 1095 },
] as const;

function PriceChart({ points, up }: { points: Array<{ date: string; close: number }>; up: boolean }) {
  if (points.length < 2) return null;
  const W = 560;
  const H = 140;
  const PAD = 6;
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const x = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2);
  const y = (c: number) => H - PAD - ((c - min) / range) * (H - PAD * 2);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join(" ");
  const area = `${PAD},${H - PAD} ${line} ${W - PAD},${H - PAD}`;
  const color = up ? "#0f6e56" : "#9f1239";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" aria-label="Price chart">
      <polygon points={area} fill={color} opacity="0.08" />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
      <circle cx={x(points.length - 1)} cy={y(closes[closes.length - 1])} r="3" fill={color} />
    </svg>
  );
}

function PerformancePanel({ brief }: { brief: ResearchBrief }) {
  const [selected, setSelected] = useState<(typeof PERF_PERIODS)[number]["key"]>("1M");
  const period = PERF_PERIODS.find((p) => p.key === selected)!;
  const value = brief.price_action[period.field] as number | null | undefined;

  const history = brief.price_history || [];
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - period.days);
  const window = history.filter((p) => new Date(p.date) >= cutoff);
  const chartPoints = window.length >= 2 ? window : history;

  return (
    <div className="mt-4 rounded-xl border border-line bg-paper/40 p-4">
      <div className="flex flex-wrap gap-1.5">
        {PERF_PERIODS.map((p) => {
          const available = brief.price_action[p.field] != null;
          const active = p.key === selected;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => setSelected(p.key)}
              disabled={!available}
              className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
                active
                  ? "bg-ink text-paper"
                  : available
                    ? "bg-white/70 text-ink/70 hover:bg-white"
                    : "cursor-not-allowed bg-white/30 text-ink/25"
              }`}
            >
              {p.key}
            </button>
          );
        })}
      </div>
      <div className="mt-4 flex items-baseline gap-3">
        <span className={`font-display text-4xl font-bold ${pctTone(value)}`}>{fmtPct(value)}</span>
        <span className="text-sm text-ink/60">
          {value == null
            ? `No ${period.label} history available`
            : `${brief.ticker} over the last ${period.label}`}
        </span>
      </div>
      <PriceChart points={chartPoints} up={(value ?? 0) >= 0} />
    </div>
  );
}

export function BriefView({ brief }: { brief: ResearchBrief }) {
  const { sources } = brief;
  const currency = brief.price_action.currency || "INR";
  return (
    <article className="space-y-8 rounded-2xl border border-line bg-white/60 p-6 shadow-sm md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
        <div>
          <h2 className="font-display text-3xl font-bold">
            {brief.ticker}
            {brief.company_name ? (
              <span className="ml-3 text-xl font-medium text-ink/60">{brief.company_name}</span>
            ) : null}
          </h2>
          <p className="mt-1 text-sm text-ink/55">
            India · NSE/BSE · As of {new Date(brief.as_of).toLocaleString()}
          </p>
        </div>
        <div
          className={`rounded-lg px-3 py-1 text-sm font-semibold uppercase tracking-wide ${
            brief.critic_passed ? "bg-accent/15 text-accent" : "bg-warn/15 text-warn"
          }`}
        >
          Critic {brief.critic_passed ? "passed" : "warnings"}
        </div>
      </header>

      <section>
        <h3 className="font-display text-xl font-semibold">Analyst summary</h3>
        <p className="mt-3 whitespace-pre-wrap leading-relaxed text-ink/85">{brief.analyst_summary}</p>
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="font-display text-xl font-semibold">
            Performance
            <Cite ids={brief.price_action.source_ids} sources={sources} />
          </h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <Stat label="Last" value={fmtMoney(brief.price_action.last_price, currency)} />
            <Stat
              label="1D"
              value={fmtPct(brief.price_action.change_1d_pct)}
              tone={pctTone(brief.price_action.change_1d_pct)}
            />
          </dl>
          <PerformancePanel brief={brief} />
        </div>
        <div>
          <h3 className="font-display text-xl font-semibold">
            Fundamentals
            <Cite ids={brief.fundamentals.source_ids} sources={sources} />
          </h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <Stat label="Market cap" value={fmtMoney(brief.fundamentals.market_cap, currency)} />
            <Stat label="P/E" value={brief.fundamentals.pe_ratio?.toFixed(2) ?? "—"} />
            <Stat label="EPS TTM" value={brief.fundamentals.eps_ttm?.toFixed(2) ?? "—"} />
            <Stat label="Margin" value={fmtPct((brief.fundamentals.profit_margin ?? 0) * 100)} />
          </dl>
        </div>
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">
          Calculations
          <Cite ids={brief.calculations.source_ids} sources={sources} />
        </h3>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Stat label="P/E (price÷EPS)" value={brief.calculations.pe_from_price_eps?.toFixed(2) ?? "—"} />
          <Stat label="YoY revenue" value={fmtPct(brief.calculations.yoy_revenue_growth)} />
          <Stat label="SMA 20" value={fmtMoney(brief.calculations.sma_20, currency)} />
          <Stat label="SMA 50" value={fmtMoney(brief.calculations.sma_50, currency)} />
        </dl>
        {brief.calculations.notes?.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-warn">
            {brief.calculations.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">
          News sentiment{" "}
          <span className="font-sans text-base font-semibold text-ink/50">
            ({brief.overall_news_sentiment || "—"})
          </span>
        </h3>
        <ul className="mt-4 space-y-4">
          {brief.news.map((n) => (
            <li
              key={n.title + (n.url || "")}
              className="rounded-xl border border-line bg-paper/30 p-4"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${
                    n.sentiment === "bullish"
                      ? "bg-accent/15 text-accent"
                      : n.sentiment === "bearish"
                        ? "bg-danger/15 text-danger"
                        : "bg-ink/5 text-ink/50"
                  }`}
                >
                  {n.sentiment}
                </span>
                {n.url ? (
                  <a href={n.url} target="_blank" rel="noreferrer" className="font-semibold underline">
                    {n.title}
                  </a>
                ) : (
                  <span className="font-semibold">{n.title}</span>
                )}
                <Cite ids={n.source_ids} sources={sources} />
              </div>
              {n.rationale && <p className="mt-2 text-sm text-ink/70">{n.rationale}</p>}
              {n.impact && (
                <p className="mt-1 text-sm font-medium text-ink/60">
                  <span className="font-semibold text-ink/70">Expected impact:</span> {n.impact}
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="font-display text-xl font-semibold">Filings &amp; results</h3>
        <div className="mt-4 space-y-4">
          {brief.filings.map((f, idx) => (
            <div
              key={`${f.form}-${f.filed_at || idx}`}
              className="rounded-xl border border-line bg-paper/30 p-4"
            >
              <p className="font-semibold">
                {f.form.replace(/_/g, " ")}
                {f.filed_at ? <span className="text-ink/55"> · {f.filed_at}</span> : null}
                <Cite ids={f.source_ids} sources={sources} />
                {f.url && (
                  <a
                    href={f.url}
                    className="ml-2 text-sm text-accent underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    View filing
                  </a>
                )}
              </p>
              {(f.risk_factors?.length ?? 0) > 0 && (
                <>
                  <p className="mt-2 text-sm font-semibold text-ink/60">Risk factors</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                    {f.risk_factors.map((r) => (
                      <li key={r.slice(0, 40)}>{r}</li>
                    ))}
                  </ul>
                </>
              )}
              {(f.mda_highlights?.length ?? 0) > 0 && (
                <>
                  <p className="mt-2 text-sm font-semibold text-ink/60">Highlights</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                    {f.mda_highlights.map((r) => (
                      <li key={r.slice(0, 40)}>{r}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ))}
        </div>
      </section>

      {brief.risks?.length > 0 && (
        <section>
          <h3 className="font-display text-xl font-semibold">Flagged risks</h3>
          <ul className="mt-4 space-y-3">
            {brief.risks.map((r) => (
              <li key={r.title + r.detail.slice(0, 24)} className="rounded-xl border border-line p-4">
                <p className="text-xs font-bold uppercase tracking-wide text-warn">{r.severity}</p>
                <p className="font-semibold">
                  {r.title}
                  <Cite ids={r.source_ids} sources={sources} />
                </p>
                <p className="mt-1 text-sm text-ink/70">{r.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="font-display text-xl font-semibold">Sources</h3>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm">
          {brief.sources.map((s) => (
            <li key={s.id}>
              <span className="font-mono text-xs text-ink/45">{s.id}</span> · {s.title}{" "}
              <span className="text-ink/45">({s.provider})</span>
              {s.url && (
                <a href={s.url} className="ml-1 text-accent underline" target="_blank" rel="noreferrer">
                  link
                </a>
              )}
            </li>
          ))}
        </ol>
      </section>

      {brief.critic_notes?.length > 0 && (
        <section className="border-t border-line pt-4 text-sm text-ink/60">
          <p className="font-semibold">Critic notes</p>
          <ul className="mt-2 list-disc pl-5">
            {brief.critic_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-paper/40 px-3 py-2">
      <dt className="text-xs uppercase tracking-wide text-ink/50">{label}</dt>
      <dd className={`mt-1 text-base font-semibold ${tone || ""}`}>{value}</dd>
    </div>
  );
}
