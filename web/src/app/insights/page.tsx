import { BacktestView } from "./BacktestView";
import { InsightsView } from "./InsightsView";

export default function InsightsPage() {
  return (
    <div className="flex flex-col gap-10">
      <h1 className="text-xl font-semibold">Insights</h1>
      <InsightsView />
      <BacktestView />
    </div>
  );
}
