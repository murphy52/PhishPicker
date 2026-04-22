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
  // Client-only optimistic flag — set while an add or undo is in flight so
  // the slot can render a pending style. Never populated by the server.
  pending?: "adding" | "removing";
}

export type PendingMutation =
  | { kind: "add"; song: EnteredSong; setNumber: string }
  | { kind: "undo"; songId: number }
  | null;

/**
 * Merge an in-flight mutation into the server preview so the UI can show
 * the user's intent immediately instead of waiting for /preview to
 * recompute (~1s on a typical show).
 *
 * - add: replace the first predicted slot in the target set with the
 *   picked song, marked pending="adding".
 * - undo: mark the last entered slot carrying songId as pending="removing".
 */
export function applyPendingMutation(
  slots: PreviewSlot[],
  pending: PendingMutation,
): PreviewSlot[] {
  if (!pending) return slots;
  const out = slots.slice();
  if (pending.kind === "add") {
    const idx = out.findIndex(
      (s) => s.set_number === pending.setNumber && s.state === "predicted",
    );
    if (idx >= 0) {
      out[idx] = {
        ...out[idx],
        state: "entered",
        entered_song: pending.song,
        pending: "adding",
      };
    }
    return out;
  }
  // undo: find the last matching entered slot
  for (let i = out.length - 1; i >= 0; i--) {
    const s = out[i];
    if (s.state === "entered" && s.entered_song?.song_id === pending.songId) {
      out[i] = { ...s, pending: "removing" };
      break;
    }
  }
  return out;
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
