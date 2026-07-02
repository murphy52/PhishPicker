import Link from "next/link";
import type { ScoreTotals } from "@/lib/score";

interface Props {
  totals: ScoreTotals;
}

/** Compact scoreboard entry point on the home screen. */
export function ScoreTeaser({ totals }: Props) {
  return (
    <Link
      href="/score"
      data-testid="score-teaser"
      className="flex items-center justify-between rounded-xl border border-neutral-800 bg-neutral-900/50 px-4 py-2.5 active:bg-neutral-800/60"
    >
      <span className="flex items-baseline gap-3">
        <span className="font-score text-sm font-semibold uppercase tracking-[0.2em] text-neutral-400">
          Scoreboard
        </span>
        <span className="font-score text-sm font-semibold text-foresight">
          🔮 {totals.foresight_total}
        </span>
        <span className="font-score text-sm font-semibold text-live">
          ⚡ {totals.live_total}
        </span>
      </span>
      <span className="flex items-baseline gap-1">
        <span
          key={totals.combined}
          className="font-score text-xl font-extrabold text-neutral-50 motion-safe:animate-[score-punch_0.7s_ease-out]"
        >
          {totals.combined}
        </span>
        <span className="text-xs text-neutral-500">pts →</span>
      </span>
    </Link>
  );
}
