import { reasonLabel, type Versus } from "@/lib/score";

export function VersusBoard({
  versus,
  final = false,
}: {
  versus: Versus;
  /** Finalized show: the header declares a winner instead of a leader. */
  final?: boolean;
}) {
  const { picker_total, phish_total, leader, per_song } = versus;
  const total = picker_total + phish_total || 1;
  const phishPct = Math.round((phish_total / total) * 100);
  const leaderLabel =
    leader === "tie"
      ? final
        ? "Tie"
        : "Dead even"
      : leader === "phish"
        ? final
          ? "Phish wins"
          : "Phish leads"
        : final
          ? "PhishPicker wins"
          : "PhishPicker leads";

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold text-emerald-400">Phish</span>
        <span data-testid="vs-leader" className="text-xs text-neutral-400">
          {leaderLabel}
        </span>
        <span className="font-semibold text-indigo-400">PhishPicker</span>
      </div>

      <div className="flex items-center gap-2">
        <span data-testid="vs-phish-total" className="w-8 text-right text-emerald-400 font-bold">
          {phish_total}
        </span>
        <div className="flex-1 h-3 rounded-full overflow-hidden bg-indigo-500">
          <div className="h-full bg-emerald-500" style={{ width: `${phishPct}%` }} />
        </div>
        <span data-testid="vs-picker-total" className="w-8 text-indigo-400 font-bold">
          {picker_total}
        </span>
      </div>

      <ul className="flex flex-col gap-1">
        {per_song.map((s) => (
          <li
            key={s.index}
            data-side={s.side}
            className={`flex items-center justify-between rounded px-3 py-2 text-sm ${
              s.side === "phish"
                ? "bg-emerald-950/40 border-l-2 border-emerald-500"
                : "bg-indigo-950/40 border-l-2 border-indigo-500"
            }`}
          >
            <span className="truncate">{s.name}</span>
            <span className="flex items-center gap-2 text-xs text-neutral-400">
              <span>{reasonLabel(s.reason)}</span>
              <span className={s.side === "phish" ? "text-emerald-400" : "text-indigo-400"}>
                +{s.points}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
