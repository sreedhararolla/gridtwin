"use client";

import { useState } from "react";
import { applyChaos, type ChaosEvent, type ScenarioName, type SloReport } from "@/lib/api";

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "America/Chicago",
  });
}

function formatInterval(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Chicago",
  });
}

function recoveryFor(event: ChaosEvent, slo: SloReport | null): string | null {
  if (event.action !== "apply") return null;
  const match = slo?.recoveries.find((r) => r.at === event.at);
  if (!match) return null;
  return match.recovery_s == null ? "recovering…" : `recovered in ${match.recovery_s.toFixed(1)} s`;
}

function EventTimeline({ events, slo }: { events: ChaosEvent[]; slo: SloReport | null }) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-500">No chaos events in this run yet.</p>;
  }
  return (
    <ol className="flex flex-col gap-1 border-l-2 border-chaos/60 pl-3 text-sm">
      {[...events].reverse().map((e) => {
        const recovery = recoveryFor(e, slo);
        return (
          <li key={`${e.at}-${e.action}`} className="flex flex-wrap items-baseline gap-x-2">
            <span className="tabular-nums text-slate-400">{formatClock(e.at)}</span>
            <span className={e.action === "apply" ? "font-medium text-chaos" : "text-slate-300"}>
              {e.scenario} · {e.action === "apply" ? "applied" : "cleared"}
            </span>
            <span className="text-slate-300">{e.target}</span>
            {e.interval_start ? (
              <span className="text-slate-500">interval {formatInterval(e.interval_start)}</span>
            ) : null}
            {recovery ? <span className="text-slate-400">· {recovery}</span> : null}
            {e.detail ? <span className="text-xs text-slate-500">{e.detail}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

function SloTable({ slo }: { slo: SloReport | null }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-1 font-medium">SLO</th>
          <th className="py-1 font-medium">Target</th>
          <th className="py-1 font-medium">Actual</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {(slo?.rows ?? []).map((row) => (
          <tr key={row.name} className="border-t border-slate-800">
            <td className="py-1 text-slate-300">{row.name}</td>
            <td className="py-1 text-slate-400">{row.target}</td>
            <td className={`py-1 font-medium ${row.ok ? "text-ok" : "text-bad"}`}>{row.actual}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Chaos buttons, the chaos event timeline and the SLO table (target vs actual).
export function ChaosPanel({
  runId,
  events,
  slo,
  onApplied,
}: {
  runId: string;
  events: ChaosEvent[];
  slo: SloReport | null;
  onApplied: () => void;
}) {
  const [arming, setArming] = useState<ScenarioName | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function apply(scenario: ScenarioName) {
    setArming(scenario);
    setError(null);
    try {
      await applyChaos(runId, scenario);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chaos apply failed");
    } finally {
      setArming(null);
    }
  }

  const buttonClass =
    "rounded border border-chaos/60 px-3 py-1 text-sm font-medium text-chaos hover:bg-chaos/10 disabled:opacity-50";

  return (
    <div className="grid gap-4 rounded border border-slate-800 bg-slate-900 p-4 md:grid-cols-2">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => apply("worker-kill")}
            disabled={arming !== null}
            className={buttonClass}
          >
            {arming === "worker-kill" ? "Waiting for a dispatch…" : "Kill worker"}
          </button>
          <span className="text-xs text-slate-500">
            Kills the worker running this run&apos;s next Shard dispatch; it restarts after a delay.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => apply("duplicate-commands")}
            disabled={arming !== null}
            className={buttonClass}
          >
            Duplicate commands
          </button>
          <span className="text-xs text-slate-500">
            Simulators deliver every batch twice and replay old ones; devices dedupe by key.
          </span>
        </div>
        {error ? <span className="text-sm text-bad">{error}</span> : null}
        <EventTimeline events={events} slo={slo} />
      </div>
      <SloTable slo={slo} />
    </div>
  );
}
