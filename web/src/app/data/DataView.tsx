"use client";

import { useEffect, useState } from "react";
import { PriceChart } from "@/components/PriceChart";
import { fetchCachedDays, fetchPrices, type CachedDay, type PricePoint } from "@/lib/api";

const SETTLEMENT_POINT = "LZ_HOUSTON";

export function DataView() {
  const [days, setDays] = useState<CachedDay[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [prices, setPrices] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCachedDays(SETTLEMENT_POINT)
      .then((cached) => {
        setDays(cached);
        setSelectedDay((current) => current ?? cached.at(-1)?.day ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedDay) return;
    fetchPrices(SETTLEMENT_POINT, selectedDay).then(setPrices);
  }, [selectedDay]);

  if (loading) {
    return <p className="text-sm text-slate-500">Loading cached days…</p>;
  }

  if (days.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No cached days yet. Run <code>make data</code>, then reload.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <label htmlFor="day-picker" className="text-sm font-medium text-slate-400">
          Day ({SETTLEMENT_POINT})
        </label>
        <select
          id="day-picker"
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
          value={selectedDay ?? ""}
          onChange={(e) => setSelectedDay(e.target.value)}
        >
          {days.map((d) => (
            <option key={d.day} value={d.day}>
              {d.day} — max ${d.max_rt_price_usd_per_mwh.toFixed(2)}/MWh
            </option>
          ))}
        </select>
      </div>
      {prices.length > 0 ? (
        <PriceChart prices={prices} />
      ) : (
        <p className="text-sm text-slate-500">No prices cached for this day.</p>
      )}
    </div>
  );
}
