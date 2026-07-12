"use client";

import { useEffect } from "react";

/**
 * Message type the service worker posts to open windows when a phish.net
 * sync push arrives (a new song landed server-side). Kept in one place so
 * sw.js and the client agree on the string.
 */
export const SYNC_MESSAGE_TYPE = "phishnet-sync";

/**
 * Run `onSync` whenever the service worker relays a phish.net sync push.
 *
 * Without this, the open app only refreshes its setlist on pull-to-refresh
 * or when the tab regains focus — so a song can land server-side (and fire a
 * notification) while the on-screen list stays stale (issue #23). This closes
 * that gap: the SW posts a message on push and the app re-hydrates at once.
 */
export function useServiceWorkerSyncMessage(onSync: () => void): void {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
      return;
    }
    // Capture the container so cleanup doesn't re-read a possibly-swapped ref.
    const sw = navigator.serviceWorker;
    const handler = (event: MessageEvent) => {
      if (event.data && event.data.type === SYNC_MESSAGE_TYPE) onSync();
    };
    sw.addEventListener("message", handler);
    return () => sw.removeEventListener("message", handler);
  }, [onSync]);
}
