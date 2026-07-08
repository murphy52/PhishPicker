"use client";

import Link from "next/link";
import { useState } from "react";
import {
  sortScorecards,
  useScorecards,
  type SortDir,
  type SortKey,
} from "@/lib/scoreHistory";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Format an ISO date (YYYY-MM-DD) without timezone drift. */
function formatShowDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

export default function HistoryPage() {
  const { scorecards, isLoading } = useScorecards();
  const [key, setKey] = useState<SortKey>("date");
  const [dir, setDir] = useState<SortDir>("desc");

  function toggle(nextKey: SortKey) {
    if (nextKey === key) {
      setDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setKey(nextKey);
      setDir("desc");
    }
  }

  const rows = sortScorecards(scorecards, key, dir);
  const arrow = (col: SortKey) =>
    key === col ? (dir === "desc" ? " ↓" : " ↑") : "";

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-300">
          ← show
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          History
        </h1>
        <span className="w-12" />
      </header>

      <main className="flex flex-1 flex-col px-4 pb-16 pt-4">
        {isLoading ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            Loading past shows…
          </p>
        ) : rows.length === 0 ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-500">
            No scored shows yet — the first finalized scoreboard lands here.
          </p>
        ) : (
          <>
            <div className="flex items-center justify-between border-b border-neutral-800 px-1 pb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-neutral-500">
              <button
                type="button"
                onClick={() => toggle("date")}
                className="hover:text-neutral-200"
              >
                Date{arrow("date")}
              </button>
              <button
                type="button"
                onClick={() => toggle("score")}
                className="hover:text-neutral-200"
              >
                Score{arrow("score")}
              </button>
            </div>
            <ol>
              {rows.map((c) => (
                <li key={c.show_id} data-testid="history-row">
                  <Link
                    href={`/score?show=${c.show_id}`}
                    className="flex items-center justify-between border-b border-neutral-900 px-1 py-3 hover:bg-neutral-900/40"
                  >
                    <span className="flex flex-col">
                      <span className="text-sm text-neutral-100">
                        {formatShowDate(c.show_date)}
                      </span>
                      <span className="text-[11px] text-neutral-600">
                        {c.foresight_total} foresight · {c.live_total} live · streak{" "}
                        {c.max_streak}
                      </span>
                    </span>
                    <span className="font-score text-xl font-extrabold tabular-nums text-neutral-100">
                      {Math.round(c.combined)}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </>
        )}
      </main>
    </div>
  );
}
