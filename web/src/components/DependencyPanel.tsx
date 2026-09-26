"use client";

import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "@/lib/api";
import { StatusDot } from "./StatusDot";

const POLL_INTERVAL_MS = 2000;

export function DependencyPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const result = await fetchHealth();
        if (!cancelled) {
          setHealth(result);
          setReachable(true);
        }
      } catch {
        if (!cancelled) setReachable(false);
      }
    }

    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!reachable) {
    return <StatusDot ok={false} label="api" detail="unreachable" />;
  }

  if (!health) {
    return <p className="text-sm text-slate-500">Loading dependency status…</p>;
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {health.dependencies.map((dep) => (
        <StatusDot key={dep.name} ok={dep.ok} label={dep.name} detail={dep.detail || undefined} />
      ))}
      {health.services.map((svc) => (
        <StatusDot
          key={svc.name}
          ok={svc.ready === svc.total && svc.total > 0}
          label={svc.name}
          detail={`${svc.ready}/${svc.total}`}
        />
      ))}
    </div>
  );
}
