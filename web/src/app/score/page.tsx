"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ComboMeter } from "@/components/ComboMeter";
import { NextCallCard, type PendingCall } from "@/components/NextCallCard";
import { ScoreFeed } from "@/components/ScoreFeed";
import { ScoreHero } from "@/components/ScoreHero";
import { useLiveShow } from "@/lib/liveShow";
import { usePreview } from "@/lib/preview";
import { buildFeedEvents, useScore, type Attribution } from "@/lib/score";

function ScoreContent() {
  // A `?show=<id>` param loads a past finalized show's board (from the history
  // page); with no param we track tonight's live show.
  const params = useSearchParams();
  const paramShow = params.get("show");
  const { showId: liveShowId } = useLiveShow();
  const showId = paramShow ?? liveShowId;
  const isHistorical = paramShow != null;

  const { data: score } = useScore(showId);
  const playedCount = score?.attributions.length ?? 0;
  // Reuses the preview cache key from the home screen; the count in the key
  // busts it when a new song lands so the pending call stays current. Skipped
  // for a past show — there is no "next call" to make.
  const { data: preview } = usePreview(isHistorical ? null : showId, playedCount);

  // A phish.net correction swaps a song at an existing index. Detect it by
  // diffing against the previous poll and pin the ↻ marker for the session —
  // the score itself is always the clean recompute.
  const prevAtts = useRef<Attribution[] | null>(null);
  const [correctedIndices, setCorrectedIndices] = useState<Set<number>>(
    () => new Set(),
  );
  useEffect(() => {
    if (!score) return;
    const prev = prevAtts.current;
    prevAtts.current = score.attributions;
    if (!prev) return;
    const byIndex = new Map(prev.map((a) => [a.index, a]));
    const changed = score.attributions
      .filter((a) => {
        const p = byIndex.get(a.index);
        return p !== undefined && p.song_id !== a.song_id;
      })
      .map((a) => a.index);
    if (changed.length > 0) {
      setCorrectedIndices((s) => new Set([...s, ...changed]));
    }
  }, [score]);

  const events = useMemo(() => {
    if (!score) return [];
    return buildFeedEvents(score.attributions).map((e) =>
      correctedIndices.has(e.index) ? { ...e, corrected: true } : e,
    );
  }, [score, correctedIndices]);

  const pendingCall: PendingCall | null = useMemo(() => {
    const slot = preview?.slots.find(
      (s) => s.state === "predicted" && s.top_k && s.top_k.length > 0,
    );
    if (!slot) return null;
    return {
      name: slot.top_k![0].name,
      setNumber: slot.set_number,
      position: slot.position,
    };
  }, [preview]);

  const streak = score?.attributions.at(-1)?.streak ?? 0;

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link
          href={isHistorical ? "/history" : "/"}
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          {isHistorical ? "← history" : "← show"}
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          Scoreboard
        </h1>
        <span className="w-12 text-right">
          {showId && !isHistorical && (
            <span
              aria-label="live"
              className="inline-block h-2 w-2 animate-pulse rounded-full bg-live"
            />
          )}
        </span>
      </header>

      <main className="flex flex-1 flex-col gap-4 px-4 pb-16">
        {!showId ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-500">
            No live show tonight — the scoreboard lights up when one starts.
          </p>
        ) : !score ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            Loading the board…
          </p>
        ) : (
          <>
            <ScoreHero totals={score.totals} frozen={score.frozen} />
            {score.frozen && (
              <Link
                href={`/predicted${showId ? `?show=${showId}` : ""}`}
                className="-mt-2 self-center text-xs text-foresight/80 hover:text-foresight"
              >
                🔮 See the pre-show bracket →
              </Link>
            )}
            {!isHistorical && (
              <NextCallCard
                call={pendingCall}
                isOpener={playedCount === 0}
                lastEvent={events[0]}
              />
            )}
            <ComboMeter streak={streak} />
            <ScoreFeed events={events} />
            <footer className="mt-4 flex justify-between text-[10px] text-neutral-700">
              <span>
                {score.totals.ppps > 0
                  ? `${score.totals.ppps.toFixed(1)} pts / predictable song`
                  : ""}
              </span>
              <span>{score.model_sha ? `model ${score.model_sha.slice(0, 7)}` : ""}</span>
            </footer>
          </>
        )}
      </main>
    </div>
  );
}

export default function ScorePage() {
  return (
    <Suspense fallback={null}>
      <ScoreContent />
    </Suspense>
  );
}
