"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChaosEvent, IntervalResult } from "@/lib/api";
import { formatCentralTime } from "@/lib/format";

// Same colour meaning on every chart (CLAUDE.md): one colour each for price, target and
// delivered. Keep these in sync with web/tailwind.config.ts.
const COLORS = { price: "#38bdf8", target: "#a78bfa", delivered: "#f59e0b" };
const CHAOS_COLOR = "#f472b6";

function formatTooltipValue(value: number, name: string): [string, string] {
  if (name === "price") return [`$${value.toFixed(2)}/MWh`, "Price"];
  if (name === "target") return [`${value.toFixed(3)} MW`, "Target"];
  return [`${value.toFixed(3)} MW`, "Delivered"];
}

export function LiveChart({
  results,
  chaosEvents = [],
}: {
  results: IntervalResult[];
  chaosEvents?: ChaosEvent[];
}) {
  // Chaos events are timeline markers on the interval they hit.
  const markers = chaosEvents.filter((e) => e.action === "apply" && e.interval_start);
  const data = results.map((r) => ({
    time: formatCentralTime(r.interval_start),
    price: r.price_usd_per_mwh,
    target: r.target_mw,
    delivered: r.delivered_mw,
  }));

  return (
    <ResponsiveContainer width="100%" height={360}>
      <LineChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
        <YAxis
          yAxisId="mw"
          stroke="#64748b"
          fontSize={12}
          label={{ value: "MW", angle: -90, position: "insideLeft", fill: "#64748b" }}
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
          formatter={formatTooltipValue}
        />
        <Legend />
        {markers.map((e) => (
          <ReferenceLine
            key={e.at}
            yAxisId="mw"
            x={formatCentralTime(e.interval_start as string)}
            stroke={CHAOS_COLOR}
            strokeDasharray="4 3"
            label={{ value: `${e.scenario} ${e.target}`, fill: CHAOS_COLOR, fontSize: 11 }}
          />
        ))}
        <Line
          yAxisId="price"
          type="monotone"
          dataKey="price"
          stroke={COLORS.price}
          dot={false}
          name="price"
        />
        <Line
          yAxisId="mw"
          type="monotone"
          dataKey="target"
          stroke={COLORS.target}
          dot={false}
          name="target"
        />
        <Line
          yAxisId="mw"
          type="monotone"
          dataKey="delivered"
          stroke={COLORS.delivered}
          dot={false}
          name="delivered"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
