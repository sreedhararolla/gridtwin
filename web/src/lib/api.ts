import { API_BASE_URL } from "./config";
import type { components } from "@/types/api";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type IntervalResult = components["schemas"]["IntervalResult"];
export type LatestRun = components["schemas"]["LatestRun"];

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  return (await res.json()) as HealthResponse;
}

export async function fetchLatestRun(): Promise<LatestRun> {
  const res = await fetch(`${API_BASE_URL}/runs/latest`, { cache: "no-store" });
  return (await res.json()) as LatestRun;
}
