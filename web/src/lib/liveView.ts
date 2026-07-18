import { useEffect, useState } from "react";

export type LiveView = "picks" | "vs";
const KEY = "phishpicker:liveView";

export function useLiveView(): [LiveView, (v: LiveView) => void] {
  const [view, setView] = useState<LiveView>("picks");

  // Read persisted choice after mount (SSR-safe — no localStorage on server).
  // Mirrors the useLiveShow hydration pattern (web/src/lib/liveShow.ts:39); the
  // set-state-in-effect lint rule must be suppressed exactly as the siblings do.
  useEffect(() => {
    const saved = localStorage.getItem(KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot SSR-safe localStorage hydration
    if (saved === "vs" || saved === "picks") setView(saved);
  }, []);

  const set = (v: LiveView) => {
    setView(v);
    localStorage.setItem(KEY, v);
  };
  return [view, set];
}
