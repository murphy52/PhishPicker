"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";

const THRESHOLD_PX = 80;
const MAX_PULL_PX = 140;
// First N pixels of finger movement map 1:1 to the indicator. After this,
// the indicator slows by DAMP_FACTOR per pixel of finger movement, creating
// the "resistance increases as you approach the trigger" feel.
const FREE_ZONE_PX = 60;
const DAMP_FACTOR = 0.5;
const HAPTIC_DURATION_MS = 12;

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
 *
 * Resistance + haptics: the indicator follows the finger 1:1 for the first
 * 60px, then damps by 0.5×, so the user feels increasing resistance as
 * they approach the trigger threshold (80px). At threshold-crossing we
 * fire navigator.vibrate(12) — a brief click on Android Chrome (and any
 * browser that ever ships the Vibration API; iOS Safari is a no-op today).
 */
export function PullToRefresh({ onRefresh, children }: Props) {
  const startYRef = useRef<number | null>(null);
  const armedRef = useRef(false);
  const wasPastThresholdRef = useRef(false);
  const [pullPx, setPullPx] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (refreshing) return;
    if (window.scrollY > 0) return;
    const t = e.touches[0];
    if (!t) return;
    startYRef.current = t.clientY;
    armedRef.current = true;
    wasPastThresholdRef.current = false;
  }, [refreshing]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!armedRef.current || startYRef.current === null) return;
    const t = e.touches[0];
    if (!t) return;
    const delta = t.clientY - startYRef.current;
    if (delta < 0) {
      armedRef.current = false;
      setPullPx(0);
      return;
    }
    const damped =
      delta <= FREE_ZONE_PX
        ? delta
        : FREE_ZONE_PX + (delta - FREE_ZONE_PX) * DAMP_FACTOR;
    const next = Math.min(damped, MAX_PULL_PX);
    setPullPx(next);
    // Single haptic click each time we cross the threshold from below.
    // Retreating below resets the latch so a second pull also clicks.
    if (next >= THRESHOLD_PX && !wasPastThresholdRef.current) {
      wasPastThresholdRef.current = true;
      if (typeof navigator !== "undefined" && "vibrate" in navigator) {
        try {
          navigator.vibrate(HAPTIC_DURATION_MS);
        } catch {
          // Some browsers throw on vibrate without a user gesture context;
          // it's a nice-to-have, never block the pull on it.
        }
      }
    } else if (next < THRESHOLD_PX) {
      wasPastThresholdRef.current = false;
    }
  }, []);

  const onTouchEnd = useCallback(async () => {
    if (!armedRef.current) {
      setPullPx(0);
      return;
    }
    const past = pullPx >= THRESHOLD_PX;
    armedRef.current = false;
    startYRef.current = null;
    wasPastThresholdRef.current = false;
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
