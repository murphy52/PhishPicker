"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";

const THRESHOLD_PX = 80;
const MAX_PULL_PX = 140;

interface Props {
  /** Called when the user pulls past the threshold and releases. Awaited. */
  onRefresh: () => Promise<unknown>;
  children: ReactNode;
}

/**
 * Touch-driven pull-to-refresh wrapper. Active only when the page is scrolled
 * to the top; below-the-fold pulls are ignored so this doesn't fight the
 * browser's normal scroll inertia. Re-pulls during an in-flight refresh are
 * a no-op so the user can't double-trigger.
 */
export function PullToRefresh({ onRefresh, children }: Props) {
  const startYRef = useRef<number | null>(null);
  const armedRef = useRef(false);
  const [pullPx, setPullPx] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (refreshing) return;
    if (window.scrollY > 0) return;
    const t = e.touches[0];
    if (!t) return;
    startYRef.current = t.clientY;
    armedRef.current = true;
  }, [refreshing]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!armedRef.current || startYRef.current === null) return;
    const t = e.touches[0];
    if (!t) return;
    const delta = t.clientY - startYRef.current;
    if (delta < 0) {
      // Upward pull is just normal scrolling — back out.
      armedRef.current = false;
      setPullPx(0);
      return;
    }
    setPullPx(Math.min(delta, MAX_PULL_PX));
  }, []);

  const onTouchEnd = useCallback(async () => {
    if (!armedRef.current) {
      setPullPx(0);
      return;
    }
    const past = pullPx >= THRESHOLD_PX;
    armedRef.current = false;
    startYRef.current = null;
    if (!past) {
      setPullPx(0);
      return;
    }
    setRefreshing(true);
    setPullPx(THRESHOLD_PX);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
      setPullPx(0);
    }
  }, [pullPx, onRefresh]);

  const past = pullPx >= THRESHOLD_PX;
  const indicatorLabel = refreshing
    ? "Refreshing…"
    : past
      ? "Release to refresh"
      : "Pull to refresh";
  const showIndicator = pullPx > 0 || refreshing;

  return (
    <div
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchEnd}
    >
      {showIndicator && (
        <div
          data-testid="ptr-indicator"
          aria-live="polite"
          className="flex items-center justify-center text-xs text-neutral-400 transition-[height] overflow-hidden"
          style={{ height: Math.max(pullPx, refreshing ? THRESHOLD_PX : 0) }}
        >
          <span
            className={
              refreshing
                ? "animate-pulse"
                : past
                  ? "text-indigo-400"
                  : "text-neutral-500"
            }
          >
            {indicatorLabel}
          </span>
        </div>
      )}
      {children}
    </div>
  );
}
