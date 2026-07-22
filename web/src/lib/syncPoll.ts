"use client";

import { useEffect } from "react";

/** Default cadence for the foreground reconciler poll. */
export const SYNC_POLL_MS = 15_000;

/** Minimum gap between client-initiated /sync/now kicks of a stalled poller. */
export const SYNC_KICK_COOLDOWN_MS = 60_000;

export interface SyncStatusLite {
  sync_enabled: boolean;
  /** Server-computed health of the reconciler: "live" (<120s since the last
   * pass), "stale", "dead", or "off". */
  state?: string;
}

/**
 * True when the client should POST /sync/now to restart a stalled reconciler.
 *
 * The server-side poller is in-memory; even with startup resume, it can stall
 * (task death, error loop). The status endpoint stamps state from
 * last_updated, so "stale"/"dead" while sync is enabled means no pass has
 * completed recently — the open app kicks it rather than waiting for the user
 * to pull-to-refresh. Cooldown-throttled so a dead phish.net API doesn't get
 * hammered every status tick.
 */
export function shouldKickSync(
  status: SyncStatusLite | null | undefined,
  lastKickMs: number,
  nowMs: number,
): boolean {
  if (!status?.sync_enabled) return false;
  if (status.state !== "stale" && status.state !== "dead") return false;
  return nowMs - lastKickMs >= SYNC_KICK_COOLDOWN_MS;
}

/**
 * While `active`, call `onPoll` every `intervalMs`.
 *
 * Used to pick up the phish.net reconciler's server-side appends in the open
 * app without waiting for a push (#23), a tab re-focus, or a manual refresh —
 * the reliable foreground path when push isn't subscribed. Gated by the caller
 * on sync being enabled, so it never fights an in-flight manual add in
 * hand-entry mode.
 */
export function useSyncPoll(
  active: boolean,
  onPoll: () => void,
  intervalMs: number = SYNC_POLL_MS,
): void {
  useEffect(() => {
    if (!active) return;
    const id = setInterval(onPoll, intervalMs);
    return () => clearInterval(id);
  }, [active, onPoll, intervalMs]);
}
