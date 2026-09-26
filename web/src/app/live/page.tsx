import { DependencyPanel } from "@/components/DependencyPanel";

export default function LivePage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Live</h1>
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-slate-400">Dependencies</h2>
        <DependencyPanel />
      </section>
    </div>
  );
}
