import { groupBracketBySet, reasonLabel, type PickOutcome } from "@/lib/score";

interface Props {
  outcomes: PickOutcome[];
  /** True once the show has ended — swaps "so far" framing for final. */
  final?: boolean;
}

/** Short outcome chip for a bracket pick, relative to what actually played. */
function outcomeChip(reason: string): { text: string; tone: string } {
  switch (reason) {
    case "opener":
    case "exact":
      return { text: reasonLabel(reason), tone: "text-foresight border-foresight/40 bg-indigo-950/30" };
    case "right_set":
      return { text: "right set", tone: "text-indigo-300/80 border-indigo-900/50 bg-indigo-950/20" };
    case "somewhere":
      return { text: "played", tone: "text-neutral-300 border-neutral-700 bg-neutral-900/40" };
    default:
      return { text: "not yet", tone: "text-neutral-600 border-neutral-800 bg-transparent" };
  }
}

/**
 * The frozen pre-show bracket, rendered as a setlist. This is what the app
 * committed to before the first note — untouched all night — with each pick
 * subtly tagged by how it landed against the real show.
 */
export function PredictedSetlist({ outcomes, final }: Props) {
  if (outcomes.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-neutral-600">
        The bracket locks when the first song is entered — nothing predicted yet.
      </p>
    );
  }
  const groups = groupBracketBySet(outcomes);
  const hits = outcomes.filter((o) => o.reason !== "absent").length;

  return (
    <div className="flex flex-col gap-5">
      <p className="text-center text-xs text-neutral-500">
        Frozen before the show · {hits} of {outcomes.length} picks{" "}
        {final ? "landed" : "landed so far"}
      </p>
      {groups.map((group) => (
        <section key={group.setNumber} data-testid="bracket-set">
          <h2 className="mb-2 font-score text-sm font-semibold uppercase tracking-[0.2em] text-neutral-400">
            {group.label}
          </h2>
          <ol className="flex flex-col gap-1">
            {group.picks.map((p) => {
              const chip = outcomeChip(p.reason);
              return (
                <li
                  key={`${p.pick.set_number}-${p.pick.position}`}
                  data-testid="bracket-pick"
                  data-hit={p.hit ? "true" : "false"}
                  className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${
                    p.hit
                      ? "border-neutral-800 bg-neutral-900/40"
                      : "border-neutral-900 bg-transparent"
                  }`}
                >
                  <span className="flex min-w-0 items-baseline gap-3">
                    <span className="w-5 shrink-0 text-right font-mono text-xs text-neutral-600">
                      {p.pick.position}
                    </span>
                    <span
                      className={`truncate font-score text-lg font-semibold ${
                        p.hit ? "text-neutral-100" : "text-neutral-500"
                      }`}
                    >
                      {p.name}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${chip.tone}`}
                  >
                    {chip.text}
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
      <p className="text-center text-[11px] text-neutral-600">
        🔮 One song per predicted slot, using the 9 / 7 / 2 default structure.
      </p>
    </div>
  );
}
