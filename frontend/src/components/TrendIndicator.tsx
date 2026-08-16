import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

/**
 * Direction is never color-only (docs/AUDIT.md #6.3) — an icon carries the
 * same signal as the color, so it still reads for color-blind users and in
 * black-and-white printouts of a research brief.
 */
export function TrendIndicator({
  value,
  suffix = "%",
  decimals = 2,
  size = "text-sm",
}: {
  value?: number | null;
  suffix?: string;
  decimals?: number;
  size?: string;
}) {
  if (value == null) return <span className="text-muted">—</span>;
  const flat = Math.abs(value) < 0.005;
  const up = value > 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const tone = flat ? "text-muted" : up ? "text-accent" : "text-danger";
  const sign = value > 0 ? "+" : "";
  return (
    <span className={`inline-flex items-center gap-0.5 font-semibold ${tone} ${size}`}>
      <Icon className="h-3.5 w-3.5 shrink-0" />
      {sign}
      {value.toFixed(decimals)}
      {suffix}
    </span>
  );
}
