/**
 * Truvest mark — three rising bars in a rounded square, matching the favicon.
 * Inline SVG (not an asset) so the brand renders on first paint with no
 * extra request and no flash of a missing logo.
 */
export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" role="img" aria-label="Truvest" className={className}>
      <rect width="32" height="32" rx="8" className="fill-ink" />
      <g className="fill-accent">
        <rect x="7" y="18" width="4" height="7" rx="1.2" />
        <rect x="14" y="13" width="4" height="12" rx="1.2" />
        <rect x="21" y="7" width="4" height="18" rx="1.2" />
      </g>
    </svg>
  );
}
