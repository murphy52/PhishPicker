import type { ScoreTotals } from "@/lib/score";

interface Props {
  totals: ScoreTotals;
  frozen: boolean;
}

/**
 * The one hero number (Foresight + Live combined) that punches on change —
 * the `key` remount retriggers the score-punch animation. The two-ledger
 * split is a smaller secondary readout; it stars in the recap, not here.
 */
export function ScoreHero({ totals, frozen }: Props) {
  return (
    <section
      data-testid="score-hero"
      className="flex flex-col items-center gap-1 pt-8 pb-4"
    >
      <span className="text-[10px] uppercase tracking-[0.35em] text-neutral-500">
        How well is the app calling tonight?
      </span>
      <span
        key={totals.combined}
        data-testid="hero-total"
        className="font-score font-extrabold text-8xl leading-none tabular-nums text-neutral-50 motion-safe:animate-[score-punch_0.7s_cubic-bezier(0.2,0.9,0.3,1.3)]"
        style={{ textShadow: "0 0 44px rgba(129, 140, 248, 0.28)" }}
      >
        {totals.combined}
      </span>
      <span className="text-[10px] uppercase tracking-[0.35em] text-neutral-600">
        points
      </span>
      <div className="mt-2 flex items-baseline gap-4 font-score text-2xl font-semibold">
        <span data-testid="foresight-total" className="text-foresight">
          <span aria-hidden="true">🔮 </span>
          {totals.foresight_total}
        </span>
        <span aria-hidden="true" className="text-neutral-700">
          ·
        </span>
        <span data-testid="live-total" className="text-live">
          <span aria-hidden="true">⚡ </span>
          {totals.live_total}
        </span>
      </div>
      {!frozen && (
        <span className="mt-1 text-xs text-neutral-500">
          the bracket locks at the first song
        </span>
      )}
    </section>
  );
}
