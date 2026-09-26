import { DataView } from "./DataView";

export default function DataPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Data</h1>
      <DataView />
    </div>
  );
}
