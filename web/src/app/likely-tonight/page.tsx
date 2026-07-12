"use client";

import Link from "next/link";
import useSWR from "swr";
import { barWidthPct, useLikelyTonight } from "@/lib/likelyTonight";

interface UpcomingShow {
  show_id: number;
  show_date: string;
  venue: string;
  city: string;
  state: string;
}

export default function LikelyTonightPage() {
  const { data: upcoming } = useSWR<UpcomingShow | null>(
    "/api/upcoming",
    async (url: string) => {
      const r = await fetch(url);
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`upcoming ${r.status}`);
      return r.json();
    },
    { revalidateOnFocus: false },
  );

  const { candidates, isLoading } = useLikelyTonight(upcoming?.show_id ?? null);
  const max = candidates.length ? candidates[0].probability : 0;

  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-300">
          ← home
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          Likely Tonight
        </h1>
        <span className="w-16" />
      </header>

      <main className="flex flex-1 flex-col gap-4 px-4 pb-16 pt-4">
        {upcoming && (
          <p className="text-center text-[10px] uppercase tracking-[0.35em] text-neutral-500">
            {upcoming.venue} · {upcoming.city}
            {upcoming.state ? `, ${upcoming.state}` : ""}
          </p>
        )}
        <p className="text-center text-xs text-neutral-500">
          Songs most likely to appear <em>anywhere</em> in the show — a different
          question than the next-song bracket.
        </p>

        {!upcoming ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-500">
            No upcoming show scheduled.
          </p>
        ) : isLoading ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            Reading the tea leaves…
          </p>
        ) : candidates.length === 0 ? (
          <p className="flex flex-1 items-center justify-center text-sm text-neutral-600">
            No prediction available yet.
          </p>
        ) : (
          <ol className="flex flex-col gap-1.5">
            {candidates.map((c, i) => (
              <li
                key={c.song_id}
                data-testid="likely-row"
                className="relative overflow-hidden rounded-md border border-neutral-800 bg-neutral-900/40 px-3 py-2"
              >
                <div
                  className="absolute inset-y-0 left-0 bg-indigo-950/40"
                  style={{ width: `${barWidthPct(c.probability, max)}%` }}
                  aria-hidden
                />
                <div className="relative flex items-center justify-between">
                  <span className="flex items-baseline gap-2">
                    <span className="w-5 text-right text-xs tabular-nums text-neutral-600">
                      {i + 1}
                    </span>
                    <span className="text-sm text-neutral-100">{c.name}</span>
                  </span>
                  <span className="text-xs tabular-nums text-neutral-400">
                    {Math.round(c.probability * 100)}%
                  </span>
                </div>
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
