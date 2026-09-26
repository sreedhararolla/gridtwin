export function StatusDot({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
      <span
        className={`h-3 w-3 shrink-0 rounded-full ${ok ? "bg-ok" : "bg-bad"}`}
        aria-label={ok ? "healthy" : "unhealthy"}
      />
      <div className="flex flex-col">
        <span className="text-sm font-medium text-slate-100">{label}</span>
        {detail ? <span className="text-xs text-slate-500">{detail}</span> : null}
      </div>
    </div>
  );
}
