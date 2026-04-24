"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { PlayedStrip } from "@/components/PlayedStrip";
import { AddSongSheet } from "@/components/AddSongSheet";
import { SetBoundaryButton } from "@/components/SetBoundaryButton";
import { ShowHeader, type UpcomingShow } from "@/components/ShowHeader";
import { FullPreview } from "@/components/FullPreview";
import { SlotAltsModal } from "@/components/SlotAltsModal";
import { SyncStatus } from "@/components/SyncStatus";
import { PushToggle } from "@/components/PushToggle";
import { useLiveShow } from "@/lib/liveShow";
import {
  applyPendingMutation,
  usePreview,
  type PendingMutation,
  type PreviewCandidate,
} from "@/lib/preview";
import { getCachedSongs, setCachedSongs, type Song } from "@/lib/songs";

interface Meta {
  shows_count: number;
  songs_count: number;
  latest_show_date: string;
  data_snapshot_at: string;
  version: string;
}

export default function Home() {
  const [songs, setSongs] = useState<Song[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [activeSlot, setActiveSlot] = useState<number | null>(null);
  const [pending, setPending] = useState<PendingMutation>(null);
  const initialized = useRef(false);
  const autoStarted = useRef(false);

  const {
    showId,
    playedSongs,
    currentSet,
    startShow,
    addSong,
    undoLast,
    advanceSet,
    clearShow,
    hydrate,
    refresh,
  } = useLiveShow();

  const { data: preview, mutate: mutatePreview } = usePreview(
    showId,
    playedSongs.length,
  );

  const { data: upcoming } = useSWR<UpcomingShow | null>(
    "/api/upcoming",
    async (url: string) => {
      const r = await fetch(url);
      if (r.status === 404) return null;
      return r.json();
    },
    { revalidateOnFocus: false, dedupingInterval: 60_000 },
  );

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

  useEffect(() => {
    if (!showId || songs.length === 0) return;
    (async () => {
      const r = await fetch(`/api/live/show/${showId}`);
      if (r.status === 404) {
        clearShow();
        return;
      }
      const data = (await r.json()) as {
        current_set: string;
        songs: { song_id: number; set_number: string; source?: string }[];
      };
      const byId = new Map(songs.map((s) => [s.song_id, s]));
      const played = data.songs
        .map((row) => {
          const song = byId.get(row.song_id);
          if (!song) return null;
          const source: "user" | "phishnet" =
            row.source === "phishnet" ? "phishnet" : "user";
          return { ...song, set_number: row.set_number, source };
        })
        .filter((s): s is NonNullable<typeof s> => s !== null);
      let currentSetFromServer = data.current_set;
      if (played.length === 0 && currentSetFromServer !== "1") {
        await fetch("/api/live/set-boundary", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ show_id: showId, set_number: "1" }),
        });
        currentSetFromServer = "1";
      }
      hydrate(played, currentSetFromServer);
    })();
  }, [showId, songs, clearShow, hydrate]);

  async function handleAdd(song: Song) {
    setPending({
      kind: "add",
      song: { song_id: song.song_id, name: song.name },
      setNumber: currentSet,
    });
    // Scroll to the pending ghost slot as soon as React flushes it — don't
    // wait for the API roundtrip. Two rAFs: one to wait for React, one more
    // in case the slot was mid-transition when the mutation fired.
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const ghost = document.querySelector(
          '[data-testid="slot"][data-pending="adding"]',
        );
        ghost?.scrollIntoView({ behavior: "smooth", block: "center" });
      }),
    );
    try {
      await addSong(song);
      await mutatePreview();
    } finally {
      setPending(null);
    }
  }

  async function handleUndo() {
    // The button targets the last un-reconciled entry — skip past any
    // phish.net-confirmed tail rows when setting up the pending marker.
    let lastUserIdx = -1;
    for (let i = playedSongs.length - 1; i >= 0; i--) {
      if (playedSongs[i].source === "user") {
        lastUserIdx = i;
        break;
      }
    }
    if (lastUserIdx === -1) return;
    setPending({ kind: "undo", songId: playedSongs[lastUserIdx].song_id });
    try {
      await undoLast();
      await mutatePreview();
    } finally {
      setPending(null);
    }
  }

  async function handleAdvanceSet(nextSet: string) {
    await advanceSet(nextSet);
    mutatePreview();
  }

  function handlePickFromAlts(candidate: PreviewCandidate) {
    handleAdd({ song_id: candidate.song_id, name: candidate.name });
    setActiveSlot(null);
  }

  useEffect(() => {
    if (showId || !upcoming || autoStarted.current) return;
    autoStarted.current = true;
    startShow(upcoming.show_date).then(() => mutatePreview());
  }, [showId, upcoming, startShow, mutatePreview]);

  // When the PWA returns to the foreground, skip the 60s poller wait:
  // kick an immediate sync pass (backend skips if sync is disabled), then
  // re-hydrate the played list and the preview so the UI shows the latest
  // phish.net state without the user having to wait for the next tick.
  useEffect(() => {
    if (!showId || !upcoming) return;
    function onVisible() {
      if (document.visibilityState !== "visible") return;
      (async () => {
        try {
          await fetch(`/api/live/show/${showId}/sync/now`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ show_date: upcoming!.show_date }),
          });
        } catch {
          // Network hiccup on resume — fall through and still re-hydrate
          // from whatever the server already has.
        }
        await refresh(songs);
        mutatePreview();
      })();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [showId, upcoming, refresh, songs, mutatePreview]);

  const slots = applyPendingMutation(preview?.slots ?? [], pending);

  return (
    <div className="min-h-dvh bg-neutral-950 text-neutral-100 flex flex-col">
      {upcoming ? (
        <div className="flex items-start justify-between gap-3 border-b border-neutral-900">
          <div className="flex-1 min-w-0">
            <ShowHeader show={upcoming} />
          </div>
          {showId && (
            <div className="px-4 pt-5 shrink-0 flex items-center gap-2">
              <PushToggle />
              <SyncStatus showId={showId} showDate={upcoming.show_date} />
            </div>
          )}
        </div>
      ) : (
        <header className="px-4 pt-6 pb-2">
          <h1 className="text-xl font-bold tracking-tight">Phishpicker</h1>
        </header>
      )}

      {showId && (
        <div className="px-4 pt-2 text-xs text-neutral-500">
          Set {currentSet} · {playedSongs.length} songs played
        </div>
      )}

      <main className="flex-1 flex flex-col gap-4 px-4 pt-3 pb-24">
        {!showId ? (
          <div className="flex flex-col items-center justify-center flex-1 gap-4">
            <p className="text-neutral-400 text-sm">
              {upcoming === undefined
                ? "Loading next show…"
                : upcoming === null
                  ? "No upcoming Phish shows."
                  : "Starting show…"}
            </p>
          </div>
        ) : (
          <>
            <PlayedStrip songs={playedSongs} onUndo={handleUndo} />

            <FullPreview
              slots={slots}
              loading={!preview}
              onSlotClick={setActiveSlot}
            />

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

      {showId && (
        <SlotAltsModal
          showId={showId}
          slotIdx={activeSlot}
          onClose={() => setActiveSlot(null)}
          onPick={handlePickFromAlts}
        />
      )}

      <footer className="px-4 py-3 text-xs text-neutral-600 border-t border-neutral-900 flex justify-between items-center">
        <span>
          {meta
            ? `${meta.shows_count} shows · ${meta.songs_count} songs · v${meta.version}`
            : "Loading…"}
        </span>
        <a href="/about" className="text-neutral-500 hover:text-indigo-400">
          about
        </a>
      </footer>
    </div>
  );
}
