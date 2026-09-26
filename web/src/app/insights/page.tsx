import { BacktestView } from "./BacktestView";
import { InsightsView } from "./InsightsView";
import { StormView } from "./StormView";

export default function InsightsPage() {
  return (
    <div className="flex flex-col gap-10">
      <h1 className="text-xl font-semibold">Insights</h1>
      <InsightsView />
      <BacktestView />
      <StormView />
    </div>
  );
}
