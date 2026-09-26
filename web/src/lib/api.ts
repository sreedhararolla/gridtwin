import { API_BASE_URL } from "./config";
import type { components } from "@/types/api";

export type HealthResponse = components["schemas"]["HealthResponse"];

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  return (await res.json()) as HealthResponse;
}
