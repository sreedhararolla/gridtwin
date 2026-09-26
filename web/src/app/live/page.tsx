import { Suspense } from "react";
import { LiveView } from "./LiveView";

export default function LivePage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
      <LiveView />
    </Suspense>
  );
}
