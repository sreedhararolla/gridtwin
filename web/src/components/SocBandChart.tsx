"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { IntervalResult } from "@/lib/api";
import { formatCentralTime } from "@/lib/format";

// SoC has its own colour (tailwind `soc`); never red, which is reserved for violations.
const SOC_COLOR = "#34d399";

function formatTooltipValue(value: number | number[], name: string): [string, string] {
  if (Array.isArray(value)) {
    return [`${value[0].toFixed(1)}% – ${value[1].toFixed(1)}%`, "SoC p10–p90"];
  }
  return [`${value.toFixed(1)}%`, name === "median" ? "SoC median" : name];
}

export function SocBandChart({ results }: { results: IntervalResult[] }) {
  const data = results.map((r) => ({
    time: formatCentralTime(r.interval_start),
    band: [r.soc_p10_pct ?? 0, r.soc_p90_pct ?? 0],
    median: r.soc_p50_pct ?? 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
        <YAxis
          domain={[0, 100]}
          stroke="#64748b"
          fontSize={12}
          label={{ value: "SoC %", angle: -90, position: "insideLeft", fill: "#64748b" }}
        />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
          formatter={formatTooltipValue}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="band"
          name="p10–p90"
          stroke="none"
          fill={SOC_COLOR}
          fillOpacity={0.25}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="median"
          name="median"
          stroke={SOC_COLOR}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
