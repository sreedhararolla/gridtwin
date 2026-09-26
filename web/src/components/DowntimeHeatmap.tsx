import type { DowntimeCell } from "@/lib/api";

// Price colour: downtime cost is a price-derived value, and red stays for violations.
const CELL_COLOR = "#38bdf8";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const monthLabel = (month: string) => {
  const [year, mon] = month.split("-");
  return `${MONTHS[Number(mon) - 1]} ${year}`;
};
export const hourLabel = (hour: number) => `${hour % 12 || 12} ${hour < 12 ? "AM" : "PM"}`;
const usdPerMin = (v: number) =>
  `$${v.toLocaleString("en-US", { maximumFractionDigits: v < 10 ? 2 : 0 })}/min`;

type Props = { cells: DowntimeCell[]; stat: "mean" | "p95" };

// Hour of day (CT) × month; opacity scales with $/min, peak cell outlined.
export function DowntimeHeatmap({ cells, stat }: Props) {
  const value = (c: DowntimeCell) => (stat === "mean" ? c.mean_usd_per_min : c.p95_usd_per_min);
  const months = [...new Set(cells.map((c) => c.month))].sort();
  const peak = cells.reduce<DowntimeCell | null>(
    (best, c) => (best === null || value(c) > value(best) ? c : best),
    null,
  );
  const max = peak ? value(peak) || 1 : 1;
  const cw = 34;
  const ch = 26;
  const left = 76;
  const top = 8;
  const width = left + 24 * cw + 8;
  const height = top + months.length * ch + 24;

  return (
    <div className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full max-w-5xl"
        role="img"
        aria-label={`Downtime cost heatmap, ${stat} $/min`}
      >
        {months.map((m, i) => (
          <text
            key={m}
            x={left - 8}
            y={top + i * ch + 17}
            fill="#94a3b8"
            fontSize={12}
            textAnchor="end"
          >
            {monthLabel(m)}
          </text>
        ))}
        {cells.map((c) => {
          const x = left + c.hour * cw;
          const y = top + months.indexOf(c.month) * ch;
          const isPeak = peak !== null && c.month === peak.month && c.hour === peak.hour;
          return (
            <rect
              key={`${c.month}-${c.hour}`}
              x={x}
              y={y}
              width={cw - 2}
              height={ch - 2}
              fill={CELL_COLOR}
              fillOpacity={0.04 + 0.96 * Math.min(1, value(c) / max)}
              stroke={isPeak ? "#e2e8f0" : "none"}
              strokeWidth={isPeak ? 2 : 0}
            >
              <title>
                {`${monthLabel(c.month)}, ${hourLabel(c.hour)} CT: mean ${usdPerMin(
                  c.mean_usd_per_min,
                )}, p95 ${usdPerMin(c.p95_usd_per_min)} (${c.intervals} intervals)`}
              </title>
            </rect>
          );
        })}
        {Array.from({ length: 8 }, (_, i) => i * 3).map((h) => (
          <text
            key={h}
            x={left + h * cw}
            y={top + months.length * ch + 16}
            fill="#94a3b8"
            fontSize={12}
          >
            {hourLabel(h)}
          </text>
        ))}
      </svg>
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span>$0/min</span>
        <span
          className="inline-block h-3 w-40 rounded"
          style={{ background: `linear-gradient(to right, ${CELL_COLOR}0a, ${CELL_COLOR})` }}
        />
        <span>{usdPerMin(max)}</span>
        {peak && (
          <span className="ml-4">
            peak (outlined): {monthLabel(peak.month)}, {hourLabel(peak.hour)} CT
          </span>
        )}
      </div>
    </div>
  );
}
