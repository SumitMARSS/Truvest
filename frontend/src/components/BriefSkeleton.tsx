import { SkeletonBlock, SkeletonCard } from "@/components/Skeleton";

/** Shown while a job is running so the page reads as "a system actively
 * working" rather than one blocking wait with nothing until the very end
 * (docs/AUDIT.md #6.2). Section shapes mirror the real BriefView layout so
 * the transition from skeleton -> real content doesn't jump around. */
export function BriefSkeleton() {
  return (
    <div className="animate-pulse space-y-8 rounded-xl border border-line bg-surface p-6 shadow-card md:p-8">
      <div className="flex items-end justify-between gap-4 border-b border-line pb-6">
        <div className="space-y-2">
          <SkeletonBlock className="h-8 w-48" />
          <SkeletonBlock className="h-4 w-64" />
        </div>
        <SkeletonBlock className="h-7 w-28" />
      </div>
      <div className="space-y-2">
        <SkeletonBlock className="h-4 w-full" />
        <SkeletonBlock className="h-4 w-full" />
        <SkeletonBlock className="h-4 w-2/3" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SkeletonCard title="Historical P/E band" lines={4} />
        <SkeletonCard title="Sector-average P/E" lines={4} />
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <SkeletonCard title="Performance" lines={5} />
        <SkeletonCard title="Fundamentals + shareholding" lines={5} />
      </div>
      <SkeletonCard title="Peer comparison" lines={4} />
      <SkeletonCard title="News sentiment" lines={4} />
    </div>
  );
}
