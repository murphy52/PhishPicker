"use client";

import useSWR from "swr";
import { RankPill } from "@/components/RankPill";

interface Slot {
  slot_idx: number;
  set_number: string;
  position: number;
  actual_song_id: number;
  actual_song: string;
  actual_rank: number | null;
}

interface ReviewPayload {
  show: {
    show_id: number;
    show_date: string;
    venue: string;
    city: string;
    state: string;
    run_position: number | null;
    run_length: number | null;
  };
  slots: Slot[];
}

const SET_LABEL: Record<string, string> = { "1": "SET 1", "2": "SET 2", E: "ENCORE" };

export default function LastShowPage() {
  const { data, error, isLoading } = useSWR<ReviewPayload>(
    "/api/last-show/review",
    async (url: string) => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    },
  );

  if (error) {
    return (
      <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
        <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
        <p className="mt-6 text-neutral-400">No completed show to review yet.</p>
      </main>
    );
  }
  if (isLoading || !data) {
    return (
      <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
        <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
        <p className="mt-6 text-neutral-500">Loading…</p>
      </main>
    );
  }

  const groups: Array<[string, Slot[]]> = [];
  for (const slot of data.slots) {
    const last = groups[groups.length - 1];
    if (last && last[0] === slot.set_number) last[1].push(slot);
    else groups.push([slot.set_number, [slot]]);
  }

  return (
    <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
      <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
      <header className="mt-4 mb-6">
        <h1 className="text-lg font-semibold">{data.show.venue}</h1>
        <p className="text-sm text-neutral-400">
          {data.show.show_date}
          {data.show.run_position && data.show.run_length && data.show.run_length > 1
            ? ` · Run: ${data.show.run_position}|${data.show.run_length}`
            : ""}
        </p>
      </header>
      {groups.map(([setNum, slots]) => (
        <section key={setNum} className="mb-6">
          <h2 className="text-xs uppercase tracking-wider text-neutral-500 mb-2">
            {SET_LABEL[setNum] ?? `SET ${setNum}`}
          </h2>
          <ul className="flex flex-col gap-2">
            {slots.map((slot) => (
              <li
                key={slot.slot_idx}
                className="flex items-center justify-between border border-neutral-800 rounded-lg px-3 py-2"
              >
                <span className="flex items-center gap-3">
                  <span className="text-xs text-neutral-500 w-5 text-right">
                    {slot.position}
                  </span>
                  <span>{slot.actual_song}</span>
                </span>
                <RankPill rank={slot.actual_rank} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
