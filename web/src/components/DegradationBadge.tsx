import type { IntervalResult } from "@/lib/api";

// The Degradation Ladder rung the latest interval dispatched on (CONTEXT.md).
const LEVELS: Record<string, { name: string; className: string }> = {
  L0: { name: "Optimized", className: "border-ok/60 text-ok" },
  L1: { name: "Cached Plan", className: "border-yellow-300/60 text-yellow-300" },
  L2: { name: "Safe Rule", className: "border-orange-400/60 text-orange-400" },
  L3: { name: "Hold · 0 MW", className: "border-bad/60 text-bad" },
};

const FEED_TEXT: Record<string, string> = {
  ok: "feed ok",
  rejected: "snapshot rejected",
  outage: "feed down",
  "circuit-open": "feed circuit open",
};

export function DegradationBadge({ latest }: { latest: IntervalResult | undefined }) {
  if (!latest) return null;
  const level = LEVELS[latest.level] ?? LEVELS.L3;
  const feed = latest.feed_status ?? "ok";
  return (
    <span
      className={`inline-flex items-center gap-2 rounded border px-2 py-0.5 text-sm font-semibold ${level.className}`}
      title={latest.feed_detail || undefined}
    >
      {latest.level} {level.name}
      <span className="text-xs font-normal text-slate-400">{FEED_TEXT[feed] ?? feed}</span>
    </span>
  );
}
