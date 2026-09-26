"use client";

import { useState } from "react";
import {
  applyChaos,
  clearChaos,
  type ApplyChaosOptions,
  type ChaosEvent,
  type IntervalResult,
  type ScenarioName,
  type SloReport,
} from "@/lib/api";

const PARTITION_PCT = 0.2;
const TELEMETRY_DELAY_S = 10;
const TELEMETRY_DELAY_PCT = 0.3;
const FEED_OUTAGE_S = 90; // wall seconds: 6 intervals at 60x, unless restored sooner
const FEED_OUTLIER_S = 15; // one interval at 60x

// Is the latest feed-outage event an apply (still broken)?
function feedOutageActive(events: ChaosEvent[]): boolean {
  const last = events.filter((e) => e.scenario === "feed-outage").at(-1);
  return last?.action === "apply";
}

type FleetEvent = {
  key: string;
  interval: string;
  text: string;
  detail?: string;
};

function mw(value: number): string {
  return `${Math.abs(value).toFixed(2)} MW`;
}

function count(n: number): string {
  return n.toLocaleString("en-US");
}

// Stale detection, re-rating and Reallocation, read off the Interval Results.
function fleetEvents(results: IntervalResult[]): FleetEvent[] {
  const out: FleetEvent[] = [];
  let previousStale = 0;
  let previousLevel = "L0";
  for (const r of results) {
    // Degradation Ladder: rejected snapshots and every level transition.
    if (r.feed_status === "rejected") {
      out.push({
        key: `${r.interval_start}-rejected`,
        interval: r.interval_start,
        text: "snapshot rejected · no dispatch on it",
        detail: r.feed_detail,
      });
    }
    if (r.level !== previousLevel) {
      out.push({
        key: `${r.interval_start}-level`,
        interval: r.interval_start,
        text: `ladder ${previousLevel} → ${r.level}`,
        detail: r.feed_detail || (r.feed_status === "ok" ? "feed clean" : r.feed_status),
      });
      previousLevel = r.level;
    }
    const stale = r.stale_devices ?? 0;
    const unresponsive = r.unresponsive_devices ?? 0;
    if (stale !== previousStale) {
      out.push({
        key: `${r.interval_start}-stale`,
        interval: r.interval_start,
        text:
          stale > previousStale
            ? `${count(stale - previousStale)} devices stale · excluded from Fleet State`
            : `${count(previousStale - stale)} devices back online`,
        detail: `${count(r.online_devices ?? 0)} online`,
      });
      previousStale = stale;
    }
    if (unresponsive > 0) {
      out.push({
        key: `${r.interval_start}-unresponsive`,
        interval: r.interval_start,
        text: `${count(unresponsive)} devices sent no ack · achievable re-rated ${mw(r.planned_achievable_mw ?? 0)} → ${mw(r.achievable_mw)}`,
      });
    }
    if ((r.reallocated_mw ?? 0) > 0) {
      const rounds = r.reallocation_rounds ?? 0;
      out.push({
        key: `${r.interval_start}-realloc`,
        interval: r.interval_start,
        text: `reallocated ${mw(r.reallocated_mw ?? 0)} to ${count(r.reallocated_devices ?? 0)} devices`,
        detail: `${rounds} round${rounds === 1 ? "" : "s"} · delivered ${mw(r.delivered_mw)}`,
      });
    }
  }
  return out;
}

function FleetTimeline({ results }: { results: IntervalResult[] }) {
  const events = fleetEvents(results);
  if (events.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No stale devices, reallocations or ladder changes yet.
      </p>
    );
  }
  return (
    <ol className="flex flex-col gap-1 border-l-2 border-slate-600 pl-3 text-sm">
      {[...events].reverse().map((e) => (
        <li key={e.key} className="flex flex-wrap items-baseline gap-x-2">
          <span className="tabular-nums text-slate-400">{formatInterval(e.interval)}</span>
          <span className="text-slate-200">{e.text}</span>
          {e.detail ? <span className="text-xs text-slate-500">{e.detail}</span> : null}
        </li>
      ))}
    </ol>
  );
}

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
  results,
  onApplied,
}: {
  runId: string;
  events: ChaosEvent[];
  slo: SloReport | null;
  results: IntervalResult[];
  onApplied: () => void;
}) {
  const [arming, setArming] = useState<ScenarioName | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function apply(scenario: ScenarioName, options: ApplyChaosOptions = {}) {
    setArming(scenario);
    setError(null);
    try {
      await applyChaos(runId, scenario, options);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chaos apply failed");
    } finally {
      setArming(null);
    }
  }

  async function restoreFeed() {
    setError(null);
    try {
      await clearChaos(runId, "feed-outage");
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Feed restore failed");
    }
  }

  const feedDown = feedOutageActive(events);

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
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => apply("partition", { pct: PARTITION_PCT })}
            disabled={arming !== null}
            className={buttonClass}
          >
            Partition {PARTITION_PCT * 100} %
          </button>
          <span className="text-xs text-slate-500">
            {PARTITION_PCT * 100} % of devices drop their commands and heartbeats; the shortfall is
            reallocated.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() =>
              apply("telemetry-delay", {
                delay_s: TELEMETRY_DELAY_S,
                pct: TELEMETRY_DELAY_PCT,
              })
            }
            disabled={arming !== null}
            className={buttonClass}
          >
            Telemetry delay {TELEMETRY_DELAY_S} s
          </button>
          <span className="text-xs text-slate-500">
            Heartbeats of {TELEMETRY_DELAY_PCT * 100} % of devices arrive {TELEMETRY_DELAY_S} s
            late; they go stale and the achievable target is de-rated.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {feedDown ? (
            <button
              type="button"
              onClick={restoreFeed}
              className="rounded border border-ok/60 px-3 py-1 text-sm font-medium text-ok hover:bg-ok/10"
            >
              Restore ERCOT feed
            </button>
          ) : (
            <button
              type="button"
              onClick={() => apply("feed-outage", { duration_s: FEED_OUTAGE_S })}
              disabled={arming !== null}
              className={buttonClass}
            >
              Break ERCOT feed
            </button>
          )}
          <span className="text-xs text-slate-500">
            The replay feed raises (up to {FEED_OUTAGE_S} s): the ladder steps L0 → L1 cached
            plan → L2 safe rule, then climbs back once the feed is clean.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => apply("feed-outlier", { duration_s: FEED_OUTLIER_S })}
            disabled={arming !== null}
            className={buttonClass}
          >
            Inject $9,999
          </button>
          <span className="text-xs text-slate-500">
            One $9,999/MWh price: the snapshot is rejected and nothing is dispatched on it.
          </span>
        </div>
        {error ? <span className="text-sm text-bad">{error}</span> : null}
        <EventTimeline events={events} slo={slo} />
        <h4 className="text-xs uppercase tracking-wide text-slate-500">Fleet timeline</h4>
        <FleetTimeline results={results} />
      </div>
      <SloTable slo={slo} />
    </div>
  );
}
