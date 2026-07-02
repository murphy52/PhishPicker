"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PredictedSetlist } from "@/components/PredictedSetlist";
import { useLiveShow } from "@/lib/liveShow";
import { useScore } from "@/lib/score";

function PredictedContent() {
  const params = useSearchParams();
  const { showId: currentShowId } = useLiveShow();
  const showId = params.get("show") ?? currentShowId;
  const { data: score } = useScore(showId);

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link
          href="/score"
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          ← scoreboard
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          The Bracket
        </h1>
        <span className="w-20" />
      </header>

      <main className="flex flex-1 flex-col gap-4 px-4 pb-16 pt-4">
        {!showId ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-500">
            No show to show a bracket for.
          </p>
        ) : !score ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            Loading the bracket…
          </p>
        ) : (
          <>
            <p className="text-center text-[10px] uppercase tracking-[0.35em] text-neutral-500">
              What the app called before the show
            </p>
            <PredictedSetlist outcomes={score.pick_outcomes} />
          </>
        )}
      </main>
    </div>
  );
}

export default function PredictedPage() {
  return (
    <Suspense fallback={null}>
      <PredictedContent />
    </Suspense>
  );
}
