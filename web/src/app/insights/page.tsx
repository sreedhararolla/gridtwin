import { BacktestView } from "./BacktestView";

export default function InsightsPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Insights</h1>
      <BacktestView />
    </div>
  );
}
