"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Leaderboard, type Candidate } from "@/components/Leaderboard";
import { PlayedStrip } from "@/components/PlayedStrip";
import { AddSongSheet } from "@/components/AddSongSheet";
import { SetBoundaryButton } from "@/components/SetBoundaryButton";
import { useLiveShow } from "@/lib/liveShow";
import { getCachedSongs, setCachedSongs, type Song } from "@/lib/songs";

interface Meta {
  shows_count: number;
  songs_count: number;
  latest_show_date: string;
  data_snapshot_at: string;
  version: string;
}

interface PredictResponse {
  candidates: Candidate[];
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export default function Home() {
  const [songs, setSongs] = useState<Song[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [starting, setStarting] = useState(false);
  const initialized = useRef(false);

  const { showId, playedSongs, currentSet, startShow, addSong, undoLast, advanceSet, clearShow } =
    useLiveShow();

  const predictKey = showId ? `/api/predict/${showId}` : null;
  const { data: prediction, mutate: mutatePrediction } = useSWR<PredictResponse>(
    predictKey,
    fetcher,
    { refreshInterval: 30_000 },
  );

  // Load songs with localStorage cache keyed on data_snapshot_at.
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    (async () => {
      const metaRes = await fetch("/api/meta");
      const m = (await metaRes.json()) as Meta;
      setMeta(m);

      const cached = getCachedSongs(m.data_snapshot_at);
      if (cached) {
        setSongs(cached);
        return;
      }
      const songRes = await fetch("/api/songs");
      const list = (await songRes.json()) as Song[];
      setSongs(list);
      setCachedSongs(m.data_snapshot_at, list);
    })().catch(console.error);
  }, []);

  // On mount with existing showId: verify it's still alive; clear if 404.
  useEffect(() => {
    if (!showId) return;
    fetch(`/api/predict/${showId}`).then((r) => {
      if (r.status === 404) clearShow();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleAdd(song: Song) {
    // Optimistic: remove from leaderboard immediately.
    mutatePrediction(
      (cur) =>
        cur
          ? { candidates: cur.candidates.filter((c) => c.song_id !== song.song_id) }
          : cur,
      false,
    );
    await addSong(song);
    mutatePrediction(); // revalidate
  }

  async function handleUndo() {
    await undoLast();
    mutatePrediction();
  }

  async function handleAdvanceSet(nextSet: string) {
    await advanceSet(nextSet);
    mutatePrediction();
  }

  async function handleStartShow() {
    setStarting(true);
    const today = new Date().toISOString().slice(0, 10);
    await startShow(today);
    setStarting(false);
    mutatePrediction();
  }

  const candidates = prediction?.candidates ?? [];

  return (
    <div className="min-h-dvh bg-neutral-950 text-neutral-100 flex flex-col">
      <header className="px-4 pt-6 pb-2">
        <h1 className="text-xl font-bold tracking-tight">Phishpicker</h1>
        {showId && (
          <p className="text-sm text-neutral-400 mt-1">
            Set {currentSet} · {playedSongs.length} songs played
          </p>
        )}
      </header>

      <main className="flex-1 flex flex-col gap-4 px-4 pb-24">
        {!showId ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-4">
            <p className="text-neutral-400 text-sm">No active show.</p>
            <button
              type="button"
              onClick={handleStartShow}
              disabled={starting}
              className="px-6 py-3 rounded-full bg-indigo-600 text-white font-medium disabled:opacity-50"
            >
              {starting ? "Starting…" : "Start show"}
            </button>
          </div>
        ) : (
          <>
            <PlayedStrip songs={playedSongs} onUndo={handleUndo} />

            {candidates.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-2">
                  Next song
                </h2>
                <Leaderboard candidates={candidates} />
              </section>
            )}

            <SetBoundaryButton currentSet={currentSet} onAdvance={handleAdvanceSet} />

            <button
              type="button"
              onClick={clearShow}
              className="text-xs text-neutral-600 hover:text-red-400 self-start mt-2"
            >
              End show
            </button>
          </>
        )}
      </main>

      {showId && <AddSongSheet songs={songs} onAdd={handleAdd} />}

      <footer className="px-4 py-3 text-xs text-neutral-600 border-t border-neutral-900">
        {meta
          ? `${meta.shows_count} shows · ${meta.songs_count} songs · v${meta.version}`
          : "Loading…"}
      </footer>
    </div>
  );
}
