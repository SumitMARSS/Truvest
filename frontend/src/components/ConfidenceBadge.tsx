import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import type { Confidence } from "@/lib/api";

const STYLES: Record<Confidence, { label: string; classes: string; Icon: typeof ShieldCheck }> = {
  high: { label: "High confidence", classes: "bg-accent/15 text-accent", Icon: ShieldCheck },
  medium: { label: "Medium confidence", classes: "bg-warn/15 text-warn", Icon: ShieldAlert },
  low: { label: "Low confidence", classes: "bg-ink/10 text-secondary", Icon: ShieldQuestion },
};

/**
 * Same visual language as the existing "Critic passed" badge — small
 * uppercase pill — so confidence reads as part of the same trust system,
 * not a bolted-on new UI idiom (spec 2.4 / 3: reuse the critic badge style).
 */
export function ConfidenceBadge({
  level,
  reason,
  className = "",
}: {
  level?: Confidence | null;
  reason?: string | null;
  className?: string;
}) {
  if (!level) return null;
  const { label, classes, Icon } = STYLES[level];
  return (
    <span
      title={reason || undefined}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${classes} ${className}`}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}
