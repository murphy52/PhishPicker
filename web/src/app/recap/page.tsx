"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { RecapView } from "@/components/RecapView";
import { useLiveShow } from "@/lib/liveShow";
import { useScorecard } from "@/lib/score";

function RecapContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { showId: currentShowId, clearShow } = useLiveShow();
  const showId = params.get("show") ?? currentShowId;
  const { data } = useScorecard(showId);
  const loaded = data && "scorecard" in data;

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-300">
          ← show
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          Recap
        </h1>
        <span className="w-12" />
      </header>

      <main className="flex flex-1 flex-col gap-4 px-4 pb-16">
        {!showId ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-500">
            No show to recap.
          </p>
        ) : !loaded ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            Tallying the night…
          </p>
        ) : (
          <>
            <RecapView data={data} />
            {showId === currentShowId && (
              <button
                type="button"
                onClick={() => {
                  clearShow();
                  router.push("/");
                }}
                className="mx-auto mt-4 rounded-lg border border-neutral-800 px-4 py-2 text-sm text-neutral-400 active:bg-neutral-800/60"
              >
                Close out the show
              </button>
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default function RecapPage() {
  return (
    <Suspense fallback={null}>
      <RecapContent />
    </Suspense>
  );
}
