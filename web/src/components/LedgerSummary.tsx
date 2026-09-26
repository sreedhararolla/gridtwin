"use client";

import { useEffect, useState } from "react";
import { fetchLedger, type IntervalResult, type LedgerIntervalSummary } from "@/lib/api";

function formatInterval(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Chicago",
  });
}

// The Command Ledger per Market Interval (issued / acked / expired / failed). It refetches
// whenever a new Interval Result arrives; pick any interval to see its row.
export function LedgerSummary({ runId, results }: { runId: string; results: IntervalResult[] }) {
  const [rows, setRows] = useState<LedgerIntervalSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const resultCount = results.length;

  useEffect(() => {
    let cancelled = false;
    fetchLedger(runId)
      .then((next) => {
        if (!cancelled) setRows(next);
      })
      .catch(() => {
        // API restarting; keep the last view
      });
    return () => {
      cancelled = true;
    };
  }, [runId, resultCount]);

  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">No Commands in the ledger yet.</p>;
  }

  const byInterval = new Map(results.map((r) => [r.interval_start, r]));
  const current = rows.find((r) => r.interval_start === selected) ?? rows.at(-1)!;
  const result = byInterval.get(current.interval_start);
  const cells: [string, string, string?][] = [
    ["Issued", current.issued.toLocaleString("en-US")],
    ["Acked", current.acked.toLocaleString("en-US")],
    ["Expired", current.expired.toLocaleString("en-US")],
    ["Failed", current.failed.toLocaleString("en-US"), current.failed > 0 ? "text-bad" : undefined],
    ["Unacked", current.unacked.toLocaleString("en-US")],
    ["Delivered", `${current.delivered_mw.toFixed(3)} MW`],
    ["Dup deliveries", (result?.duplicate_deliveries ?? 0).toLocaleString("en-US")],
    [
      "Dup effects",
      (result?.duplicate_effects ?? 0).toLocaleString("en-US"),
      (result?.duplicate_effects ?? 0) > 0 ? "text-bad" : "text-ok",
    ],
  ];

  return (
    <div className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900 p-4">
      <label className="flex items-center gap-2 text-sm text-slate-400">
        Interval
        <select
          value={current.interval_start}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-200"
        >
          {rows.map((r) => (
            <option key={r.interval_start} value={r.interval_start}>
              {formatInterval(r.interval_start)} CT
            </option>
          ))}
        </select>
        {selected === null ? <span className="text-xs text-slate-500">(latest)</span> : null}
      </label>
      <dl className="grid grid-cols-4 gap-3 text-sm md:grid-cols-8">
        {cells.map(([label, value, cls]) => (
          <div key={label} className="flex flex-col">
            <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
            <dd className={`font-medium tabular-nums ${cls ?? "text-slate-100"}`}>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
