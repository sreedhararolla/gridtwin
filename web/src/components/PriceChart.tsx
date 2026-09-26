"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricePoint } from "@/lib/api";

// Same colour meaning as every other chart (CLAUDE.md): one colour for price.
// RT and DAM are both "price"; solid vs dashed tells them apart.
const PRICE_COLOR = "#38bdf8";

function formatCentralTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Chicago",
  });
}

function formatTooltipValue(value: unknown, name: unknown): [string, string] {
  const label = name === "rt" ? "RT" : "DAM";
  return [typeof value === "number" ? `$${value.toFixed(2)}/MWh` : "—", label];
}

export function PriceChart({ prices }: { prices: PricePoint[] }) {
  const data = prices.map((p) => ({
    time: formatCentralTime(p.interval_start),
    rt: p.rt_price_usd_per_mwh,
    dam: p.dam_price_usd_per_mwh,
  }));

  return (
    <ResponsiveContainer width="100%" height={360}>
      <LineChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
        <YAxis
          stroke="#64748b"
          fontSize={12}
          label={{ value: "$/MWh", angle: -90, position: "insideLeft", fill: "#64748b" }}
        />
        <Tooltip
          contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
          formatter={formatTooltipValue}
        />
        <Legend />
        <Line type="monotone" dataKey="rt" stroke={PRICE_COLOR} dot={false} name="rt" />
        <Line
          type="monotone"
          dataKey="dam"
          stroke={PRICE_COLOR}
          strokeDasharray="6 4"
          dot={false}
          name="dam"
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
