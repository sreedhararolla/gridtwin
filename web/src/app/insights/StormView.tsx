"use client";

import { useEffect, useState } from "react";
import { MemberCard } from "@/components/MemberCard";
import { fetchBacktest, type BacktestReport } from "@/lib/api";
import { formatCentralTime } from "@/lib/format";

const usd = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;

// Storm mode's trade-off panel: $ forgone vs backup hours gained, straight from the
// backtest's lp vs lp_storm schedules (the same numbers `make backtest` prints).
export function StormView() {
  const [report, setReport] = useState<BacktestReport | null | undefined>(undefined);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetchBacktest()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  const config = report?.storm_config;
  if (!report || !config || !report.storm || report.storm.length === 0) return null;

  const days = [...report.storm].sort((a, b) => b.tradeoff.usd_forgone - a.tradeoff.usd_forgone);
  const current = days.find((d) => d.day === selected) ?? days[0];
  const forgone = days.reduce((sum, d) => sum + d.tradeoff.usd_forgone, 0);
  const gained = days.map((d) => d.tradeoff.backup_hours_gained).sort((a, b) => a - b);
  const medianGained = gained[Math.floor(gained.length / 2)];

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">Storm mode: what the reserve costs</h2>
        <p className="text-sm text-slate-400">
          The Reserve Floor rises from {current.base_floor_pct.toFixed(0)}% to{" "}
          {current.max_floor_pct.toFixed(0)}% up to {(config.lead_intervals * 15) / 60} h before
          an interval with p(spike) ≥ {Math.round(config.risk_threshold * 100)}%, or at ≥{" "}
          {config.heat_threshold_c} °C / ≤ {config.cold_threshold_c} °C. lp_storm vs lp on{" "}
          {days.length} days: {usd(forgone)} forgone in total, median +{medianGained.toFixed(1)} h
          of backup per home (at {config.home_backup_load_kw} kW).
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <table className="w-full max-w-3xl text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th className="py-1 font-medium">Day</th>
              <th className="py-1 text-right font-medium">Floor raised (h)</th>
              <th className="py-1 text-right font-medium">lp ($)</th>
              <th className="py-1 text-right font-medium">lp_storm ($)</th>
              <th className="py-1 text-right font-medium">$ forgone</th>
              <th className="py-1 text-right font-medium">Backup lp → storm (h)</th>
              <th className="py-1 text-right font-medium">Backup gained (h)</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {days.slice(0, 10).map((d) => (
              <tr
                key={d.day}
                onClick={() => setSelected(d.day)}
                className={`cursor-pointer border-t border-slate-800 ${
                  d.day === current.day ? "bg-slate-800/60" : "hover:bg-slate-900"
                }`}
              >
                <td className="py-1">{d.day}</td>
                <td className="py-1 text-right">{((d.raised_intervals * 15) / 60).toFixed(2)}</td>
                <td className="py-1 text-right">{usd(d.lp_value_usd)}</td>
                <td className="py-1 text-right">{usd(d.lp_storm_value_usd)}</td>
                <td className="py-1 text-right">{usd(d.tradeoff.usd_forgone)}</td>
                <td className="py-1 text-right">
                  {d.tradeoff.backup_hours_base.toFixed(1)} → {d.tradeoff.backup_hours_storm.toFixed(1)}
                </td>
                <td className="py-1 text-right">+{d.tradeoff.backup_hours_gained.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {current.card ? (
          <MemberCard
            card={current.card}
            caption={`${current.day}, floor raised at ${formatCentralTime(current.first_raised_utc)} CT`}
          />
        ) : null}
      </div>
    </section>
  );
}
