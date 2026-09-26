import type { IntervalResult } from "@/lib/api";

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function Readout({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="flex flex-col rounded border border-slate-800 bg-slate-900 px-4 py-3">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <span className="text-2xl font-semibold tabular-nums text-slate-100">{value}</span>
      {detail ? <span className="text-xs text-slate-500">{detail}</span> : null}
    </div>
  );
}

// Online devices, shard fan-out and dispatch latency against the interval's wall budget.
export function FleetReadouts({ results }: { results: IntervalResult[] }) {
  const latest = results.at(-1);
  if (!latest) return null;

  const budgetS = (latest.budget_ms ?? 0) / 1000;
  const latestS = latest.latency_ms / 1000;
  const medianS = median(results.map((r) => r.latency_ms)) / 1000;
  const budgetPct = budgetS > 0 ? (100 * medianS) / budgetS : 0;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Readout
        label="Online devices"
        value={(latest.online_devices ?? 0).toLocaleString("en-US")}
        detail="non-stale, in Fleet State"
      />
      <Readout
        label="Shards dispatched"
        value={`${latest.shard_count ?? 0}`}
        detail={`${latest.acked_count.toLocaleString("en-US")} acks this interval`}
      />
      <Readout
        label="Dispatch latency"
        value={`${latestS.toFixed(2)} s`}
        detail={`this interval · budget ${budgetS.toFixed(1)} s`}
      />
      <Readout
        label="Median latency"
        value={`${budgetPct.toFixed(1)} %`}
        detail={`${medianS.toFixed(2)} s of ${budgetS.toFixed(1)} s wall budget`}
      />
    </div>
  );
}
