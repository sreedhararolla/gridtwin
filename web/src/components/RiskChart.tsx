"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchRiskDay, type IntervalResult, type RiskDay } from "@/lib/api";

// Same colour meaning as every other chart (CLAUDE.md): price is sky; the Risk Curve gets
// its own colour. Realized spikes are price markers, not red (red = violations/errors).
const PRICE_COLOR = "#38bdf8";
const RISK_COLOR = "#fde047";
const INTERVAL_MS = 15 * 60 * 1000;

function centralDay(iso: string): string {
  // en-CA formats as YYYY-MM-DD
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: "America/Chicago" });
}

function centralTime(ms: number): string {
  return new Date(ms).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Chicago",
  });
}

type Row = {
  t: number;
  ahead: number | null;
  now: number | null;
  price: number | null;
  spike: number | null;
};

function formatTooltipValue(value: unknown, name: unknown): [string, string] {
  if (typeof value !== "number") return ["—", String(name)];
  if (name === "RT price" || name === "realized spike") {
    return [`$${value.toFixed(2)}/MWh`, String(name)];
  }
  return [`${value.toFixed(1)}%`, String(name)];
}

/** The Risk Curve for the replay day: p(spike) made one hour ahead for every interval,
 * the current Risk Curve over the next 4 h, and the realized spikes (RT above the
 * model's p99 threshold). */
export function RiskChart({ results }: { results: IntervalResult[] }) {
  const first = results.at(0);
  const latest = results.at(-1);
  const day = first ? centralDay(first.interval_start) : null;
  const [risk, setRisk] = useState<RiskDay | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (!day) return;
    let cancelled = false;
    fetchRiskDay(day)
      .then((r) => {
        if (cancelled) return;
        setRisk(r);
        setMissing(r === null);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [day]);

  if (missing) {
    return (
      <p className="text-sm text-slate-500">
        No Risk Curve for this day. Run <code>make train</code>.
      </p>
    );
  }
  if (!risk) return <p className="text-sm text-slate-500">Loading Risk Curve…</p>;

  const nowMs = latest ? new Date(latest.interval_start).getTime() : null;
  const current = nowMs
    ? risk.points.find((p) => new Date(p.interval_start).getTime() === nowMs)
    : undefined;
  const curveNow = new Map<number, number>();
  current?.curve.forEach((p, k) => curveNow.set(nowMs! + k * INTERVAL_MS, p));

  const data: Row[] = risk.points.map((p) => {
    const t = new Date(p.interval_start).getTime();
    const now = curveNow.get(t);
    return {
      t,
      ahead: p.p_spike_1h_ahead == null ? null : 100 * p.p_spike_1h_ahead,
      now: now == null ? null : 100 * now,
      price: p.rt_price_usd_per_mwh ?? null,
      spike: p.spike ? (p.rt_price_usd_per_mwh ?? null) : null,
    };
  });

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-500">
        Spike = RT above ${risk.threshold_usd_per_mwh.toFixed(2)}/MWh (training p99) ·{" "}
        {risk.provenance} model
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={centralTime}
            stroke="#64748b"
            fontSize={12}
          />
          <YAxis
            yAxisId="p"
            domain={[0, 100]}
            stroke="#64748b"
            fontSize={12}
            label={{ value: "p(spike) %", angle: -90, position: "insideLeft", fill: "#64748b" }}
          />
          <YAxis
            yAxisId="price"
            orientation="right"
            stroke="#64748b"
            fontSize={12}
            label={{ value: "$/MWh", angle: 90, position: "insideRight", fill: "#64748b" }}
          />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
            labelFormatter={(v) => centralTime(Number(v))}
            formatter={formatTooltipValue}
          />
          <Legend />
          {nowMs ? <ReferenceLine yAxisId="p" x={nowMs} stroke="#64748b" /> : null}
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="price"
            name="RT price"
            stroke={PRICE_COLOR}
            strokeOpacity={0.5}
            dot={false}
            isAnimationActive={false}
          />
          <Scatter
            yAxisId="price"
            dataKey="spike"
            name="realized spike"
            fill={PRICE_COLOR}
            isAnimationActive={false}
          />
          <Line
            yAxisId="p"
            type="monotone"
            dataKey="ahead"
            name="p(spike) 1 h ahead"
            stroke={RISK_COLOR}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            yAxisId="p"
            type="monotone"
            dataKey="now"
            name="Risk Curve now (next 4 h)"
            stroke={RISK_COLOR}
            strokeDasharray="6 4"
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
