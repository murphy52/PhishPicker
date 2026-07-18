import type { LiveView } from "@/lib/liveView";

export function LiveViewToggle({
  value,
  onChange,
}: {
  value: LiveView;
  onChange: (v: LiveView) => void;
}) {
  const seg = (v: LiveView, label: string) => (
    <button
      type="button"
      aria-pressed={value === v}
      onClick={() => onChange(v)}
      className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors ${
        value === v ? "bg-neutral-700 text-white" : "text-neutral-400"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="flex gap-1 rounded-lg bg-neutral-900 p-1">
      {seg("picks", "Picks")}
      {seg("vs", "VS")}
    </div>
  );
}
