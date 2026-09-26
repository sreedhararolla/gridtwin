"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "./config";
import type { IntervalResult } from "./api";

/** Subscribes to a Replay Run's Interval Results over SSE (ADR-003: browser connects
 * straight to FastAPI). The stream replays the backlog first, then pushes live updates. */
export function useIntervalResults(runId: string | null) {
  const [results, setResults] = useState<IntervalResult[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!runId) {
      setResults([]);
      return;
    }
    setResults([]);
    const source = new EventSource(`${API_BASE_URL}/runs/${runId}/events`);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event: MessageEvent<string>) => {
      const result = JSON.parse(event.data) as IntervalResult;
      setResults((prev) => {
        const next = prev.filter((r) => r.interval_start !== result.interval_start);
        next.push(result);
        next.sort((a, b) => a.interval_start.localeCompare(b.interval_start));
        return next;
      });
    };

    return () => source.close();
  }, [runId]);

  return { results, connected };
}
