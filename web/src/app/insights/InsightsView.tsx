"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DowntimeHeatmap } from "@/components/DowntimeHeatmap";
import { fetchInsights, type InsightsReport } from "@/lib/api";

const PRICE_COLOR = "#38bdf8";
const usd = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;
const pct = (v: number) => `${v.toFixed(1)}%`;

export function InsightsView() {
  const [report, setReport] = useState<InsightsReport | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [stat, setStat] = useState<"mean" | "p95">("mean");

  useEffect(() => {
    fetchInsights()
      .then(setReport)
      .catch(() => setError("API unavailable"));
  }, []);

  if (error) return <p className="text-sm text-bad">{error}</p>;
  if (report === undefined) return <p className="text-sm text-slate-500">Loading insights…</p>;
  if (report === null) {
    return (
      <p className="text-sm text-slate-500">
        No insights yet. Run <code>make insights</code>, then reload.
      </p>
    );
  }

  const post = report.concentration.find((c) => c.regime === "post_rtcb");

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-medium">What most people miss</h2>
        <p className="text-sm text-slate-400">
          {report.settlement_point} · {report.start_day} → {report.end_day} · post-RTC+B ·{" "}
          {report.device_count.toLocaleString()} Devices, {report.fleet_mw.toFixed(1)} MW
        </p>
        {report.headline && (
          <p className="mt-3 max-w-4xl text-xl font-medium text-slate-100">
            {report.headline.text}
          </p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-slate-400">Value concentration</h3>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-400">
              <tr>
                <th className="py-1 font-medium">Regime</th>
                <th className="py-1 text-right font-medium">Intervals</th>
                <th className="py-1 text-right font-medium">Opportunity ($)</th>
                {post?.top_intervals.map((t) => (
                  <th key={t.top_pct} className="py-1 text-right font-medium">
                    Top {t.top_pct}% (%)
                  </th>
                ))}
                <th className="py-1 text-right font-medium">Top 10 days (%)</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {report.concentration.map((c) => (
                <tr key={c.regime} className="border-t border-slate-800">
                  <td className="py-1">{c.regime === "post_rtcb" ? "post-RTC+B" : "pre-RTC+B"}</td>
                  <td className="py-1 text-right">{c.intervals.toLocaleString()}</td>
                  <td className="py-1 text-right">{usd(c.total_opportunity_usd)}</td>
                  {c.top_intervals.map((t) => (
                    <td key={t.top_pct} className="py-1 text-right">
                      {pct(t.share_pct)}
                    </td>
                  ))}
                  <td className="py-1 text-right">{pct(c.top_days_share_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {report.concentration.length === 1 && (
            <p className="text-xs text-slate-500">
              Pre-RTC+B history is not cached, so there is no regime comparison
              (MARKETDATA_INCLUDE_PRE_RTCB=true, then <code>make data</code>).
            </p>
          )}
          {post && (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={post.curve} margin={{ top: 8, right: 24, bottom: 16, left: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="intervals_pct"
                  stroke="#64748b"
                  fontSize={12}
                  tickFormatter={(v: number) => `${v}%`}
                  label={{
                    value: "top intervals by Opportunity (% of intervals)",
                    position: "insideBottom",
                    offset: -8,
                    fill: "#64748b",
                    fontSize: 12,
                  }}
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={12}
                  domain={[0, 100]}
                  tickFormatter={(v: number) => `${v}%`}
                  label={{
                    value: "% of window value",
                    angle: -90,
                    position: "insideLeft",
                    fill: "#64748b",
                    fontSize: 12,
                  }}
                />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                  labelFormatter={(v: unknown) => `top ${String(v)}% of intervals`}
                  formatter={(v: unknown) => [
                    typeof v === "number" ? pct(v) : "—",
                    "share of value",
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="value_pct"
                  stroke={PRICE_COLOR}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {post && (
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-medium text-slate-400">
              Top {post.top_days.length} days ({pct(post.top_days_share_pct)} of the value in{" "}
              {post.days} days)
            </h3>
            <table className="w-full text-sm">
              <thead className="text-left text-slate-400">
                <tr>
                  <th className="py-1 font-medium">#</th>
                  <th className="py-1 font-medium">Day</th>
                  <th className="py-1 text-right font-medium">Opportunity ($)</th>
                  <th className="py-1 text-right font-medium">Share (%)</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {post.top_days.map((d, i) => (
                  <tr key={d.day} className="border-t border-slate-800">
                    <td className="py-1">{i + 1}</td>
                    <td className="py-1">{d.day}</td>
                    <td className="py-1 text-right">{usd(d.opportunity_usd)}</td>
                    <td className="py-1 text-right">{pct(d.share_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-medium text-slate-400">
            Downtime cost: expected $ lost per minute of dispatch outage, hour of day (CT) × month
          </h3>
          <div className="flex gap-1 text-xs">
            {(["mean", "p95"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStat(s)}
                className={`rounded px-2 py-0.5 ${
                  stat === s ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:bg-slate-800"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <DowntimeHeatmap cells={report.downtime} stat={stat} />
      </div>

      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-slate-400">Forecast error vs price</h3>
        <p className="text-sm text-slate-500">{report.forecast_error.reason}</p>
      </div>

      <div className="flex max-w-4xl flex-col gap-1 text-sm text-slate-400">
        <h3 className="font-medium">Definitions</h3>
        <p>
          <span className="text-slate-200">Opportunity</span> of a Market Interval = fleet MW ×
          max(0, RT SPP − that trading day&apos;s median RT SPP) × 0.25 h, in $. Fleet MW ={" "}
          {report.device_count.toLocaleString()} Devices × their max power ={" "}
          {report.fleet_mw.toFixed(1)} MW.
        </p>
        <p>
          <span className="text-slate-200">Top N% share</span> = Opportunity in the ⌈N% × intervals⌉
          highest-Opportunity intervals ÷ the window&apos;s total Opportunity.{" "}
          <span className="text-slate-200">Top 10 days</span> = the same, summing Opportunity per
          Central-time trading day.
        </p>
        <p>
          <span className="text-slate-200">Downtime cost</span> ($/min) = Opportunity ÷ 15 min: a
          minute of dispatch outage loses 1/15 of its interval&apos;s Opportunity. Each cell is
          the mean (or p95, linear interpolation) over that month&apos;s intervals starting in that
          hour, Central time.
        </p>
        <p className="text-xs text-slate-500">
          Numbers come from <code>make insights</code>, which also exports them as CSV (and the
          heatmap as SVG) in <code>data/cache/insights/</code>.
        </p>
      </div>
    </section>
  );
}
