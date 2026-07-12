"use client";

import { useEffect } from "react";

/** Default cadence for the foreground reconciler poll. */
export const SYNC_POLL_MS = 15_000;

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
