"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchBacktest, type BacktestReport, type DayResult } from "@/lib/api";

// One colour per Strategy on every Insights chart. None reuses price/target/delivered,
// and red stays reserved for violations and errors.
const STRATEGY_COLORS: Record<string, string> = {
  naive: "#94a3b8",
  lp: "#2dd4bf",
  perfect_foresight: "#e2e8f0",
};
const STRATEGY_LABELS: Record<string, string> = {
  naive: "naive",
  lp: "lp",
  perfect_foresight: "perfect foresight",
};
const DAYS_PER_MONTH = 365.25 / 12;

const usd = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;

type MonthRow = { month: string } & Record<string, number | string>;

// $/MW-month for each calendar month of the window, per Strategy.
function byMonth(days: DayResult[], fleetMw: number): MonthRow[] {
  const months = new Map<string, Map<string, { value: number; days: number }>>();
  for (const d of days) {
    const month = d.day.slice(0, 7);
    const strategies = months.get(month) ?? new Map();
    const agg = strategies.get(d.strategy) ?? { value: 0, days: 0 };
    agg.value += d.value_usd;
    agg.days += 1;
    strategies.set(d.strategy, agg);
    months.set(month, strategies);
  }
  return [...months.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, strategies]) => {
      const row: MonthRow = { month };
      for (const [strategy, agg] of strategies) {
        row[strategy] = agg.value / fleetMw / (agg.days / DAYS_PER_MONTH);
      }
      return row;
    });
}

// The days where the LP's plan was furthest from perfect foresight, worst first.
function worstLpDays(days: DayResult[], n: number) {
  const byDay = new Map<string, Record<string, number>>();
  for (const d of days) {
    byDay.set(d.day, { ...(byDay.get(d.day) ?? {}), [d.strategy]: d.value_usd });
  }
  return [...byDay.entries()]
    .map(([day, v]) => ({
      day,
      naive: v.naive ?? 0,
      lp: v.lp ?? 0,
      perfect_foresight: v.perfect_foresight ?? 0,
    }))
    .sort((a, b) => b.perfect_foresight - b.lp - (a.perfect_foresight - a.lp))
    .slice(0, n);
}

export function BacktestView() {
  const [report, setReport] = useState<BacktestReport | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBacktest()
      .then(setReport)
      .catch(() => setError("API unavailable"));
  }, []);

  if (error) return <p className="text-sm text-bad">{error}</p>;
  if (report === undefined) return <p className="text-sm text-slate-500">Loading backtest…</p>;
  if (report === null) {
    return (
      <p className="text-sm text-slate-500">
        No backtest yet. Run <code>make backtest</code>, then reload.
      </p>
    );
  }

  const months = byMonth(report.days, report.fleet_mw);
  const worst = worstLpDays(report.days, 8);

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">Strategy backtest</h2>
        <p className="text-sm text-slate-400">
          {report.settlement_point} · {report.start_day} → {report.end_day} · fleet aggregate{" "}
          {report.fleet_mw.toFixed(1)} MW / {report.fleet_mwh.toFixed(1)} MWh · each day starts at{" "}
          {report.start_soc_pct.toFixed(0)}% SoC · degradation $
          {report.degradation_usd_per_mwh.toFixed(0)}/MWh · naive discharges at ≥ $
          {report.naive_discharge_threshold_usd.toFixed(0)}/MWh, charges at ≤ $
          {report.naive_charge_threshold_usd.toFixed(0)}/MWh · 96-interval LP solve p50{" "}
          {report.lp_solve_ms_p50.toFixed(1)} ms (max {report.lp_solve_ms_max.toFixed(1)} ms)
        </p>
      </div>

      <table className="w-full max-w-3xl text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-1 font-medium">Strategy</th>
            <th className="py-1 text-right font-medium">Days</th>
            <th className="py-1 text-right font-medium">Value ($)</th>
            <th className="py-1 text-right font-medium">$/MW-month</th>
            <th className="py-1 text-right font-medium">Discharged (MWh)</th>
            <th className="py-1 text-right font-medium">% of perfect foresight</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {report.summary.map((s) => (
            <tr key={s.strategy} className="border-t border-slate-800">
              <td className="py-1">
                <span
                  className="mr-2 inline-block h-2 w-2 rounded-full"
                  style={{ background: STRATEGY_COLORS[s.strategy] }}
                />
                {STRATEGY_LABELS[s.strategy] ?? s.strategy}
              </td>
              <td className="py-1 text-right">{s.days}</td>
              <td className="py-1 text-right">{usd(s.value_usd)}</td>
              <td className="py-1 text-right">{usd(s.usd_per_mw_month)}</td>
              <td className="py-1 text-right">{Math.round(s.discharged_mwh).toLocaleString()}</td>
              <td className="py-1 text-right">{s.share_of_perfect_foresight_pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <h3 className="text-sm font-medium text-slate-400">$/MW-month by month</h3>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={months} margin={{ top: 8, right: 24, bottom: 8, left: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="month" stroke="#64748b" fontSize={12} />
            <YAxis
              stroke="#64748b"
              fontSize={12}
              tickFormatter={(v: number) => usd(v)}
              label={{ value: "$/MW-month", angle: -90, position: "insideLeft", fill: "#64748b" }}
            />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
              formatter={(value: unknown, name: unknown) => [
                typeof value === "number" ? `${usd(value)}/MW-month` : "—",
                STRATEGY_LABELS[String(name)] ?? String(name),
              ]}
            />
            <Legend formatter={(name: string) => STRATEGY_LABELS[name] ?? name} />
            {Object.keys(STRATEGY_COLORS).map((s) => (
              <Bar key={s} dataKey={s} fill={STRATEGY_COLORS[s]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h3 className="text-sm font-medium text-slate-400">
          Days where the LP left the most on the table ($ per day)
        </h3>
        <table className="w-full max-w-3xl text-sm">
          <thead className="text-left text-slate-400">
            <tr>
              <th className="py-1 font-medium">Day</th>
              <th className="py-1 text-right font-medium">naive ($)</th>
              <th className="py-1 text-right font-medium">lp ($)</th>
              <th className="py-1 text-right font-medium">perfect foresight ($)</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {worst.map((d) => (
              <tr key={d.day} className="border-t border-slate-800">
                <td className="py-1">{d.day}</td>
                <td className="py-1 text-right">{usd(d.naive)}</td>
                <td className="py-1 text-right">{usd(d.lp)}</td>
                <td className="py-1 text-right">{usd(d.perfect_foresight)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
