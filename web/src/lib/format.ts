// Timestamps arrive in UTC; the dashboard always displays Central time (docs/SPEC.md).
export function formatCentralTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Chicago",
  });
}
