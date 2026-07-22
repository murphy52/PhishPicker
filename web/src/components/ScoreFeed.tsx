"use client";

import { useState } from "react";
import { KIND_EMOJI, type FeedEvent } from "@/lib/score";

const COACH_KEY = "phishpicker:score_coach_seen";

interface Props {
  events: FeedEvent[];
}

/**
 * The beat-by-beat story of the night, newest first. Every scoring event
 * states the claim it beat so best-claim-wins reads as self-evident, and the
 * first event of the night annotates itself once (coach mark, not a manual).
 */
export function ScoreFeed({ events }: Props) {
  const [coachSeen, setCoachSeen] = useState(() => {
    if (typeof window === "undefined") return true;
    return localStorage.getItem(COACH_KEY) === "1";
  });

  if (events.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-neutral-600">
        Nothing on the board yet — points land as songs do.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {!coachSeen && (
        <div
          data-testid="coach-mark"
          className="flex items-start justify-between gap-3 rounded-xl border border-indigo-900/60 bg-indigo-950/30 px-4 py-3 text-xs text-indigo-200/90"
        >
          <p>
            First points! <span className="text-foresight">🔮 Foresight</span>{" "}
            is the app&apos;s pre-show bracket,{" "}
            <span className="text-live">⚡ Live</span> is its next-song calls.
            Every song banks its single best claim — never both.
          </p>
          <button
            type="button"
            onClick={() => {
              localStorage.setItem(COACH_KEY, "1");
              setCoachSeen(true);
            }}
            className="shrink-0 rounded-md border border-indigo-800 px-2 py-1 text-indigo-300 active:bg-indigo-900/50"
          >
            got it
          </button>
        </div>
      )}
      <ul data-testid="score-feed" className="flex flex-col gap-1.5">
        {events.map((e) => (
          <FeedRow key={e.index} event={e} />
        ))}
      </ul>
    </div>
  );
}

function FeedRow({ event: e }: { event: FeedEvent }) {
  const isMiss = e.kind === "miss";
  const isBustout = e.kind === "bustout";
  return (
    <li
      data-testid="feed-event"
      data-kind={e.kind}
      className={`rounded-lg border px-3 py-2 motion-safe:animate-[feed-in_0.35s_ease-out] ${
        isBustout
          ? "border-bustout/40 bg-yellow-950/20"
          : isMiss
            ? "border-neutral-900 bg-transparent opacity-60"
            : e.kind === "foresight"
              ? "border-indigo-900/50 bg-indigo-950/20"
              : "border-amber-900/40 bg-amber-950/15"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-2">
          <span aria-hidden="true" className="shrink-0 text-sm">
            {KIND_EMOJI[e.kind]}
          </span>
          <span
            className={`truncate font-score text-lg font-semibold ${
              isMiss ? "text-neutral-500" : "text-neutral-100"
            }`}
          >
            {e.name}
          </span>
          {e.corrected && (
            <span
              data-testid="corrected-badge"
              className="shrink-0 text-[10px] text-neutral-500"
              title="corrected against phish.net"
            >
              ↻ corrected
            </span>
          )}
        </span>
        {e.points > 0 ? (
          <span
            className={`shrink-0 font-score text-lg font-extrabold ${
              e.kind === "foresight" ? "text-foresight" : "text-live"
            }`}
          >
            +{e.points}
            {e.mult != null && e.mult > 1 ? (
              <span className="ml-1 text-xs font-semibold opacity-80">
                ×{e.mult}
              </span>
            ) : null}
          </span>
        ) : (
          <span className="shrink-0 text-xs text-neutral-600">—</span>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-6 text-[11px]">
        <span
          className={
            isBustout
              ? "bg-[linear-gradient(110deg,#a16207_20%,#fde68a_50%,#a16207_80%)] bg-[length:200%_100%] bg-clip-text font-semibold uppercase tracking-wider text-transparent motion-safe:animate-[bustout-shine_2.5s_linear_infinite]"
              : isMiss
                ? "uppercase tracking-wider text-neutral-600"
                : e.kind === "foresight"
                  ? "uppercase tracking-wider text-indigo-300/80"
                  : "uppercase tracking-wider text-amber-300/80"
          }
        >
          {e.headline}
        </span>
        {isBustout && (
          <span className="text-neutral-500">nobody calls those — no penalty</span>
        )}
        {e.beaten && <span className="text-neutral-500">({e.beaten})</span>}
        {e.sequenceStreak != null && (
          <span
            data-testid="sequence-badge"
            className="font-semibold text-foresight motion-safe:animate-[feed-in_0.35s_ease-out]"
          >
            🔥 exact sequence — {e.sequenceStreak} in a row
          </span>
        )}
        {e.foreseen && (
          <span data-testid="foreseen-badge" className="text-foresight">
            ✓ foreseen — streak holds
          </span>
        )}
        {e.calledEarly && (
          <span data-testid="early-badge" className="text-neutral-400">
            🔭 called it early
          </span>
        )}
      </div>
    </li>
  );
}
