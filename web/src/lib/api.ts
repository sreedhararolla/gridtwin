import { API_BASE_URL } from "./config";
import type { components } from "@/types/api";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type IntervalResult = components["schemas"]["IntervalResult"];
export type LatestRun = components["schemas"]["LatestRun"];
export type CachedDay = components["schemas"]["CachedDay"];
export type PricePoint = components["schemas"]["PricePoint"];
export type StartedRun = components["schemas"]["StartedRun"];
export type ChaosEvent = components["schemas"]["ChaosEvent"];
export type SloReport = components["schemas"]["SloReport"];
export type LedgerIntervalSummary = components["schemas"]["LedgerIntervalSummary"];
export type ScenarioName = components["schemas"]["ApplyChaosRequest"]["scenario"];
export type Strategy = NonNullable<components["schemas"]["StartRunRequest"]["strategy"]>;
export type BacktestReport = components["schemas"]["BacktestReport"];
export type StrategySummary = components["schemas"]["StrategySummary"];
export type DayResult = components["schemas"]["DayResult"];

export async function fetchLedger(runId: string): Promise<LedgerIntervalSummary[]> {
  const res = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/ledger`, {
    cache: "no-store",
  });
  return (await res.json()) as LedgerIntervalSummary[];
}

export type ApplyChaosOptions = Pick<
  components["schemas"]["ApplyChaosRequest"],
  "pct" | "delay_s" | "duration_s"
>;

export async function applyChaos(
  runId: string,
  scenario: ScenarioName,
  options: ApplyChaosOptions = {},
): Promise<ChaosEvent> {
  const res = await fetch(`${API_BASE_URL}/chaos/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario, run_id: runId, ...options }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `chaos apply failed: ${res.status}`);
  }
  return (await res.json()) as ChaosEvent;
}

export async function clearChaos(runId: string, scenario: ScenarioName): Promise<ChaosEvent> {
  const res = await fetch(`${API_BASE_URL}/chaos/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario, run_id: runId }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `chaos clear failed: ${res.status}`);
  }
  return (await res.json()) as ChaosEvent;
}

export async function fetchChaosEvents(runId: string): Promise<ChaosEvent[]> {
  const res = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/chaos-events`, {
    cache: "no-store",
  });
  return (await res.json()) as ChaosEvent[];
}

export async function fetchSlo(runId: string): Promise<SloReport> {
  const res = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/slo`, {
    cache: "no-store",
  });
  return (await res.json()) as SloReport;
}

export async function startRun(day: string, strategy: Strategy): Promise<StartedRun> {
  const body: components["schemas"]["StartRunRequest"] = { day, strategy };
  const res = await fetch(`${API_BASE_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`start run failed: ${res.status}`);
  return (await res.json()) as StartedRun;
}

// null = no backtest yet (`make backtest` has not been run).
export async function fetchBacktest(): Promise<BacktestReport | null> {
  const res = await fetch(`${API_BASE_URL}/insights/backtest`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`backtest failed: ${res.status}`);
  return (await res.json()) as BacktestReport;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  return (await res.json()) as HealthResponse;
}

export async function fetchLatestRun(): Promise<LatestRun> {
  const res = await fetch(`${API_BASE_URL}/runs/latest`, { cache: "no-store" });
  return (await res.json()) as LatestRun;
}

export async function fetchCachedDays(settlementPoint: string): Promise<CachedDay[]> {
  const res = await fetch(
    `${API_BASE_URL}/marketdata/days?settlement_point=${encodeURIComponent(settlementPoint)}`,
    { cache: "no-store" },
  );
  return (await res.json()) as CachedDay[];
}

export async function fetchPrices(settlementPoint: string, day: string): Promise<PricePoint[]> {
  const params = new URLSearchParams({
    settlement_point: settlementPoint,
    day,
  });
  const res = await fetch(`${API_BASE_URL}/marketdata/prices?${params}`, {
    cache: "no-store",
  });
  return (await res.json()) as PricePoint[];
}
