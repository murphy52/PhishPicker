"use client";

import useSWR from "swr";

export interface PreviewCandidate {
  song_id: number;
  name: string;
  probability: number;
  score: number;
  rank: number;
}

export interface EnteredSong {
  song_id: number;
  name: string;
}

export interface PreviewSlot {
  slot_idx: number;
  set_number: string;
  position: number;
  state: "entered" | "predicted";
  entered_song?: EnteredSong;
  top_k?: PreviewCandidate[];
}

export interface PreviewResponse {
  slots: PreviewSlot[];
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function usePreview(showId: string | null, playedCount: number) {
  const key = showId ? `/api/live/show/${showId}/preview?_n=${playedCount}` : null;
  return useSWR<PreviewResponse>(key, fetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 1_000,
    // Keep the prior preview on screen while refetching for a new key —
    // /preview takes several seconds, and flashing to the skeleton on every
    // song add is jarring.
    keepPreviousData: true,
  });
}
