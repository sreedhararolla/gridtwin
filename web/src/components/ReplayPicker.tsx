"use client";

import { useEffect, useState } from "react";
import { fetchCachedDays, startRun, type CachedDay } from "@/lib/api";

const SETTLEMENT_POINT = "LZ_HOUSTON";

// Any-day replay: pick a cached day (spikiest first) and start a Replay Run of the full fleet.
export function ReplayPicker({ onStarted }: { onStarted: (runId: string) => void }) {
  const [days, setDays] = useState<CachedDay[]>([]);
  const [day, setDay] = useState<string>("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCachedDays(SETTLEMENT_POINT)
      .then((cached) => {
        const bySpike = [...cached].sort(
          (a, b) => b.max_rt_price_usd_per_mwh - a.max_rt_price_usd_per_mwh,
        );
        setDays(bySpike);
        setDay((current) => current || (bySpike[0]?.day ?? ""));
      })
      .catch(() => setError("API unavailable"));
  }, []);

  async function replay() {
    setStarting(true);
    setError(null);
    try {
      const run = await startRun(day);
      onStarted(run.run_id);
    } catch {
      setError("Could not start the run");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor="replay-day" className="text-sm font-medium text-slate-400">
        Replay day ({SETTLEMENT_POINT})
      </label>
      <select
        id="replay-day"
        className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
        value={day}
        onChange={(e) => setDay(e.target.value)}
        disabled={days.length === 0}
      >
        {days.map((d) => (
          <option key={d.day} value={d.day}>
            {d.day} — max ${d.max_rt_price_usd_per_mwh.toFixed(2)}/MWh
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={replay}
        disabled={!day || starting}
        className="rounded bg-slate-700 px-3 py-1 text-sm font-medium text-slate-100 hover:bg-slate-600 disabled:opacity-50"
      >
        {starting ? "Starting…" : "Replay"}
      </button>
      {error ? <span className="text-sm text-bad">{error}</span> : null}
    </div>
  );
}
