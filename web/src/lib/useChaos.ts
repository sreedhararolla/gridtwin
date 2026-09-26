"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchChaosEvents, fetchSlo, type ChaosEvent, type SloReport } from "./api";

const POLL_MS = 2000;

// The run's chaos event log and SLO table, polled: both change on chaos actions and on
// each new Interval Result, and a 2 s refresh is plenty at 15 s per interval.
export function useChaos(runId: string | null) {
  const [events, setEvents] = useState<ChaosEvent[]>([]);
  const [slo, setSlo] = useState<SloReport | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const [nextEvents, nextSlo] = await Promise.all([fetchChaosEvents(runId), fetchSlo(runId)]);
      setEvents(nextEvents);
      setSlo(nextSlo);
    } catch {
      // API restarting; keep the last view and try again on the next tick
    }
  }, [runId]);

  useEffect(() => {
    setEvents([]);
    setSlo(null);
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { events, slo, refresh };
}
