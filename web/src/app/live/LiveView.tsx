"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { DependencyPanel } from "@/components/DependencyPanel";
import { LiveChart } from "@/components/LiveChart";
import { fetchLatestRun } from "@/lib/api";
import { useIntervalResults } from "@/lib/useIntervalResults";

const LATEST_RUN_POLL_MS = 3000;

export function LiveView() {
  const searchParams = useSearchParams();
  const runParam = searchParams.get("run");
  const [runId, setRunId] = useState<string | null>(runParam);

  useEffect(() => {
    if (runParam) {
      setRunId(runParam);
      return;
    }
    let cancelled = false;
    async function poll() {
      try {
        const latest = await fetchLatestRun();
        if (!cancelled && latest.run_id) setRunId(latest.run_id);
      } catch {
        // no run yet, or the API is still coming up; keep polling
      }
    }
    poll();
    const id = setInterval(poll, LATEST_RUN_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runParam]);

  const { results, connected } = useIntervalResults(runId);
  const latest = results.at(-1);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Live</h1>
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-slate-400">Dependencies</h2>
        <DependencyPanel />
      </section>
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-400">
            {runId ? `Run ${runId}` : "Waiting for a replay run…"}
          </h2>
          {latest ? (
            <span className="text-xs text-slate-500">
              Level {latest.level} · {results.length} intervals ·{" "}
              {connected ? "live" : "reconnecting"}
            </span>
          ) : null}
        </div>
        {runId ? (
          <LiveChart results={results} />
        ) : (
          <p className="text-sm text-slate-500">
            Run <code>make demo</code> to start a replay.
          </p>
        )}
      </section>
    </div>
  );
}
