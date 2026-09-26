"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChaosPanel } from "@/components/ChaosPanel";
import { DependencyPanel } from "@/components/DependencyPanel";
import { FleetReadouts } from "@/components/FleetReadouts";
import { LedgerSummary } from "@/components/LedgerSummary";
import { LiveChart } from "@/components/LiveChart";
import { ReplayPicker } from "@/components/ReplayPicker";
import { SocBandChart } from "@/components/SocBandChart";
import { fetchLatestRun } from "@/lib/api";
import { useChaos } from "@/lib/useChaos";
import { useIntervalResults } from "@/lib/useIntervalResults";

const LATEST_RUN_POLL_MS = 3000;

export function LiveView() {
  const router = useRouter();
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
  const { events, slo, refresh } = useChaos(runId);
  const latest = results.at(-1);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Live</h1>
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-slate-400">Dependencies</h2>
        <DependencyPanel />
      </section>
      <section className="flex flex-col gap-3">
        <ReplayPicker onStarted={(id) => router.push(`/live?run=${encodeURIComponent(id)}`)} />
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
          <>
            <FleetReadouts results={results} />
            <h3 className="text-sm font-medium text-slate-400">Chaos</h3>
            <ChaosPanel
              runId={runId}
              events={events}
              slo={slo}
              results={results}
              onApplied={refresh}
            />
            <h3 className="text-sm font-medium text-slate-400">Command Ledger</h3>
            <LedgerSummary runId={runId} results={results} />
            <LiveChart results={results} chaosEvents={events} />
            <h3 className="text-sm font-medium text-slate-400">Fleet SoC (p10 / median / p90)</h3>
            <SocBandChart results={results} />
          </>
        ) : (
          <p className="text-sm text-slate-500">
            Pick a day above, or run <code>make demo DAY=YYYY-MM-DD</code>.
          </p>
        )}
      </section>
    </div>
  );
}
