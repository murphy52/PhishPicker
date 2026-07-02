import type { Attribution, FinalizeResponse } from "@/lib/score";
import { reasonLabel, recapBreakdown } from "@/lib/score";

/**
 * The post-show scorecard: same engine output as the live board, retold as
 * the night's story — ledger breakdowns, streak highlight, and the
 * self-deprecating "songs that beat the app" list.
 */
export function RecapView({ data }: { data: FinalizeResponse }) {
  const { scorecard, context, result } = data;
  const recap = recapBreakdown(result);
  const showRank = context.shows_scored > 1;
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col items-center gap-1 pt-6">
        <span className="text-[10px] uppercase tracking-[0.35em] text-neutral-500">
          Final scorecard · {scorecard.show_date}
        </span>
        <span
          data-testid="recap-total"
          className="font-score text-8xl font-extrabold leading-none tabular-nums text-neutral-50"
          style={{ textShadow: "0 0 44px rgba(129, 140, 248, 0.28)" }}
        >
          {scorecard.combined}
        </span>
        {showRank &&
          (context.is_best ? (
            <span
              data-testid="best-badge"
              className="mt-1 rounded-full border border-bustout/50 bg-yellow-950/30 px-3 py-0.5 font-score text-sm font-semibold uppercase tracking-widest text-bustout"
            >
              🏆 Best yet
            </span>
          ) : (
            <span data-testid="rank-line" className="mt-1 text-xs text-neutral-500">
              #{context.rank_by_total} of {context.shows_scored} shows scored ·
              best {context.best_total}
            </span>
          ))}
        <div className="mt-2 flex items-baseline gap-4 font-score text-2xl font-semibold">
          <span className="text-foresight">🔮 {scorecard.foresight_total}</span>
          <span aria-hidden="true" className="text-neutral-700">
            ·
          </span>
          <span className="text-live">⚡ {scorecard.live_total}</span>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-2 text-center">
        <Stat label="pts / predictable song" value={scorecard.ppps.toFixed(1)} />
        <Stat
          label="hottest run"
          value={
            scorecard.max_streak > 0 ? `${scorecard.max_streak} in a row` : "—"
          }
        />
      </div>

      <Section
        title="🔮 Foresight — the frozen bracket"
        rows={recap.foresight}
        tone="foresight"
        empty="The bracket never connected tonight."
      />
      <Section
        title="⚡ Live — next-song calls"
        rows={recap.live}
        tone="live"
        empty="No live catches tonight."
      />
      <Section
        title="🎸 Songs that beat the app"
        rows={recap.beatTheApp}
        tone="beat"
        empty="Nothing got past the app. Suspicious."
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-neutral-800/80 bg-neutral-900/40 px-3 py-3">
      <div className="font-score text-2xl font-extrabold text-neutral-100">
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-widest text-neutral-500">
        {label}
      </div>
    </div>
  );
}

function Section({
  title,
  rows,
  tone,
  empty,
}: {
  title: string;
  rows: Attribution[];
  tone: "foresight" | "live" | "beat";
  empty: string;
}) {
  return (
    <section data-testid={`recap-section-${tone}`}>
      <h2 className="mb-2 font-score text-sm font-semibold uppercase tracking-[0.2em] text-neutral-400">
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="text-xs text-neutral-600">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((a) => (
            <li
              key={a.index}
              data-testid="recap-row"
              className="flex items-baseline justify-between gap-2 rounded-lg border border-neutral-900 bg-neutral-900/30 px-3 py-1.5"
            >
              <span className="flex min-w-0 items-baseline gap-2">
                <span
                  className={`truncate font-score text-base font-semibold ${
                    tone === "beat" && !a.bustout
                      ? "text-neutral-500"
                      : "text-neutral-100"
                  }`}
                >
                  {a.name}
                </span>
                <span className="shrink-0 text-[10px] uppercase tracking-wider text-neutral-500">
                  {a.bustout
                    ? "bustout — celebrated, not counted"
                    : a.reason
                      ? reasonLabel(a.reason).toLowerCase()
                      : "missed"}
                </span>
              </span>
              {a.final > 0 && (
                <span
                  className={`shrink-0 font-score text-base font-extrabold ${
                    tone === "foresight" ? "text-foresight" : "text-live"
                  }`}
                >
                  +{a.final}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
