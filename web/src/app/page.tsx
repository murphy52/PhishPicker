"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { PlayedStrip } from "@/components/PlayedStrip";
import { AddSongSheet } from "@/components/AddSongSheet";
import { ShowHeader, type UpcomingShow } from "@/components/ShowHeader";
import { FullPreview } from "@/components/FullPreview";
import { PullToRefresh } from "@/components/PullToRefresh";
import { SlotAltsModal } from "@/components/SlotAltsModal";
import { ScoreTeaser } from "@/components/ScoreTeaser";
import { VersusBoard } from "@/components/VersusBoard";
import { LiveViewToggle } from "@/components/LiveViewToggle";
import { useLiveView } from "@/lib/liveView";
import { useLiveShow, isStaleLiveShow } from "@/lib/liveShow";
import { badgesBySlot, useScore } from "@/lib/score";
import {
  applyPendingMutation,
  usePreview,
  type PendingMutation,
  type PreviewCandidate,
} from "@/lib/preview";
import { getCachedSongs, setCachedSongs, type Song } from "@/lib/songs";
import { useServiceWorkerSyncMessage } from "@/lib/syncMessage";
import { useSyncPoll } from "@/lib/syncPoll";

interface Meta {
  shows_count: number;
  songs_count: number;
  latest_show_date: string;
  data_snapshot_at: string;
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

  const { data: score } = useScore(showId, playedSongs.length);
  // Same icons as the score feed, on the picks view's entered slots — the
  // drama unfolds without leaving the main screen.
  const scoreBadges = useMemo(
    () => (score ? badgesBySlot(score.attributions) : undefined),
    [score],
  );

  const [liveView, setLiveView] = useLiveView();

  // Sync state — shares its SWR key with SyncStatus, so this doesn't add a
  // second poll. Gates the foreground reconciler poll below.
  const { data: syncStatus } = useSWR<{ sync_enabled: boolean } | null>(
    showId ? `/api/live/show/${showId}/sync/status` : null,
    (url: string) => fetch(url).then((r) => r.json()),
    { refreshInterval: 5_000, revalidateOnFocus: false },
  );

  const { data: upcoming, mutate: mutateUpcoming } = useSWR<UpcomingShow | null>(
    "/api/upcoming",
    async (url: string) => {
      const r = await fetch(url);
      if (r.status === 404) return null;
      return r.json();
    },
    { revalidateOnFocus: false, dedupingInterval: 60_000 },
  );

  const { data: lastShow } = useSWR<{ show_id: number } | null>(
    "/api/last-show",
    async (url: string) => {
      const r = await fetch(url);
      if (r.status === 404) return null;
      return r.json();
    },
    { revalidateOnFocus: false, dedupingInterval: 60_000 },
  );

  // Force-refresh on user pull. Mirrors the visibilitychange handler but
  // also revalidates /api/upcoming so a date-rollover (e.g. midnight on a
  // residency-night gap) shows up immediately.
  const handlePullRefresh = useCallback(async () => {
    if (!showId) {
      await mutateUpcoming();
      return;
    }
    if (upcoming) {
      try {
        await fetch(`/api/live/show/${showId}/sync/now`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ show_date: upcoming.show_date }),
        });
      } catch {
        // Best-effort — fall through to local refresh either way.
      }
    }
    await Promise.all([refresh(songs), mutatePreview(), mutateUpcoming()]);
  }, [showId, upcoming, songs, refresh, mutatePreview, mutateUpcoming]);

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
        show_date: string;
        current_set: string;
        songs: { song_id: number; set_number: string; source?: string }[];
      };
      // Self-heal when localStorage points at yesterday's residency-night
      // showId. The show row still exists in the live DB so we won't get
      // a 404 — compare the date directly against today's upcoming and
      // clear if they disagree. The auto-start effect below will then
      // create a fresh show for tonight.
      if (isStaleLiveShow(data, upcoming)) {
        clearShow();
        return;
      }
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
  }, [showId, songs, upcoming, clearShow, hydrate]);

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

  async function handleSetChange(nextSet: string) {
    if (nextSet === currentSet) return;
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

  // A phish.net sync push means a new song landed server-side. The service
  // worker relays it here so the open list updates at once, instead of the
  // user having to pull-to-refresh or re-focus the tab (issue #23). The
  // server appends before pushing, so a plain re-hydrate is enough.
  useServiceWorkerSyncMessage(
    useCallback(() => {
      if (!showId) return;
      refresh(songs);
      mutatePreview();
    }, [showId, refresh, songs, mutatePreview]),
  );

  // Foreground fallback for the reconciler: while sync is enabled, poll the
  // live show so server-side appends land in the UI even when push isn't
  // subscribed (the setInterval pauses in a backgrounded tab, where the push
  // above takes over). refresh() grows playedSongs, which re-keys the
  // count-based preview + score queries so they refetch automatically.
  useSyncPoll(
    !!showId && (syncStatus?.sync_enabled ?? false),
    useCallback(() => {
      if (showId) refresh(songs);
    }, [showId, refresh, songs]),
  );

  const slots = applyPendingMutation(preview?.slots ?? [], pending);

  return (
    <PullToRefresh onRefresh={handlePullRefresh}>
    <div className="min-h-dvh bg-neutral-950 text-neutral-100 flex flex-col">
      {upcoming ? (
        <ShowHeader show={upcoming} liveShowId={showId} />
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

      <main className="flex-1 flex flex-col gap-4 px-4 pt-3 pb-28">
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
        ) : liveView === "vs" ? (
          <>
            {score?.versus ? (
              <VersusBoard versus={score.versus} />
            ) : (
              <p className="text-neutral-400 text-sm py-8 text-center">
                Freeze your bracket to start the matchup.
              </p>
            )}
            <PlayedStrip songs={playedSongs} onUndo={handleUndo} />
            <a
              href={`/recap?show=${showId}`}
              className="text-xs text-neutral-600 hover:text-indigo-400 self-start mt-2"
            >
              End show → recap
            </a>
          </>
        ) : (
          <>
            {score && score.attributions.length > 0 && (
              <ScoreTeaser totals={score.totals} />
            )}

            <PlayedStrip songs={playedSongs} onUndo={handleUndo} />

            <FullPreview
              slots={slots}
              currentSet={currentSet}
              loading={!preview}
              onSlotClick={setActiveSlot}
              onSetChange={handleSetChange}
              scoreBadges={scoreBadges}
            />

            <a
              href={`/recap?show=${showId}`}
              className="text-xs text-neutral-600 hover:text-indigo-400 self-start mt-2"
            >
              End show → recap
            </a>
          </>
        )}
      </main>

      {showId && (
        <div className="fixed bottom-6 left-4 right-24 z-40">
          <LiveViewToggle value={liveView} onChange={setLiveView} />
        </div>
      )}

      {showId && <AddSongSheet songs={songs} onAdd={handleAdd} />}

      {showId && (
        <SlotAltsModal
          showId={showId}
          slotIdx={activeSlot}
          onClose={() => setActiveSlot(null)}
          onPick={handlePickFromAlts}
        />
      )}

      <footer
        // pb clears the fixed Picks/VS toggle (bottom-6 + ~46px tall) so the
        // links stay clickable at the end of the scroll; normal pb otherwise.
        className={`px-4 pt-3 pr-24 text-xs text-neutral-600 border-t border-neutral-900 flex flex-col gap-1 items-end ${
          showId ? "pb-24" : "pb-3"
        }`}
      >
        <span>
          {meta
            ? `${meta.shows_count} shows · ${meta.songs_count} songs · web ${
                (process.env.NEXT_PUBLIC_GIT_SHA ?? "dev").slice(0, 7)
              }`
            : "Loading…"}
        </span>
        <span className="flex gap-2">
          {lastShow ? (
            <>
              <a href="/last-show" className="text-neutral-500 hover:text-indigo-400">
                last show
              </a>
              <span className="text-neutral-700">·</span>
            </>
          ) : null}
          <a href="/history" className="text-neutral-500 hover:text-indigo-400">
            history
          </a>
          <span className="text-neutral-700">·</span>
          <a href="/likely-tonight" className="text-neutral-500 hover:text-indigo-400">
            likely tonight
          </a>
          <span className="text-neutral-700">·</span>
          <a href="/about" className="text-neutral-500 hover:text-indigo-400">
            about
          </a>
        </span>
      </footer>
    </div>
    </PullToRefresh>
  );
}
