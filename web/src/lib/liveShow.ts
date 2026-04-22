"use client";

import { useCallback, useEffect, useState } from "react";
import type { Song } from "./songs";

const LS_KEY = "phishpicker:live_show_id";

export interface LiveSong extends Song {
  set_number: string;
}

export function useLiveShow() {
  const [showId, setShowId] = useState<string | null>(null);
  const [playedSongs, setPlayedSongs] = useState<LiveSong[]>([]);
  const [currentSet, setCurrentSet] = useState("1");

  useEffect(() => {
    const stored = localStorage.getItem(LS_KEY);
    if (stored) setShowId(stored);
  }, []);

  const startShow = useCallback(async (show_date: string, venue_id?: number) => {
    const res = await fetch("/api/live/show", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ show_date, venue_id }),
    });
    const data = (await res.json()) as { show_id: string };
    localStorage.setItem(LS_KEY, data.show_id);
    setShowId(data.show_id);
    setPlayedSongs([]);
    setCurrentSet("1");
    return data.show_id;
  }, []);

  const addSong = useCallback(
    async (song: Song) => {
      if (!showId) return;
      await fetch("/api/live/song", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ show_id: showId, song_id: song.song_id, set_number: currentSet }),
      });
      setPlayedSongs((prev) => [...prev, { ...song, set_number: currentSet }]);
    },
    [showId, currentSet],
  );

  const undoLast = useCallback(async () => {
    if (!showId || playedSongs.length === 0) return;
    await fetch(`/api/live/song/last?show_id=${showId}`, { method: "DELETE" });
    setPlayedSongs((prev) => prev.slice(0, -1));
  }, [showId, playedSongs]);

  const advanceSet = useCallback(
    async (nextSet: string) => {
      if (!showId) return;
      await fetch("/api/live/set-boundary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ show_id: showId, set_number: nextSet }),
      });
      setCurrentSet(nextSet);
    },
    [showId],
  );

  const clearShow = useCallback(() => {
    localStorage.removeItem(LS_KEY);
    setShowId(null);
    setPlayedSongs([]);
    setCurrentSet("1");
  }, []);

  return { showId, playedSongs, currentSet, startShow, addSong, undoLast, advanceSet, clearShow };
}
