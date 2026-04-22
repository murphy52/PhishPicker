"use client";

import { useEffect } from "react";

/**
 * Register the root-scoped service worker so push notifications can be
 * delivered when the PWA isn't in the foreground. Kept as a null-rendering
 * component so it can be dropped anywhere in the tree (layout.tsx) without
 * affecting layout.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator))
      return;
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("service worker registration failed:", err);
    });
  }, []);
  return null;
}
