import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useSyncPoll } from "./syncPoll";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("polls on the interval while active", () => {
  const onPoll = vi.fn();
  renderHook(() => useSyncPoll(true, onPoll, 1000));
  expect(onPoll).not.toHaveBeenCalled();
  vi.advanceTimersByTime(3000);
  expect(onPoll).toHaveBeenCalledTimes(3);
});

test("does not poll when inactive", () => {
  const onPoll = vi.fn();
  renderHook(() => useSyncPoll(false, onPoll, 1000));
  vi.advanceTimersByTime(5000);
  expect(onPoll).not.toHaveBeenCalled();
});

test("stops polling on unmount", () => {
  const onPoll = vi.fn();
  const { unmount } = renderHook(() => useSyncPoll(true, onPoll, 1000));
  vi.advanceTimersByTime(1000);
  expect(onPoll).toHaveBeenCalledTimes(1);
  unmount();
  vi.advanceTimersByTime(5000);
  expect(onPoll).toHaveBeenCalledTimes(1);
});

test("stops polling when it goes inactive", () => {
  const onPoll = vi.fn();
  const { rerender } = renderHook(
    ({ active }) => useSyncPoll(active, onPoll, 1000),
    { initialProps: { active: true } },
  );
  vi.advanceTimersByTime(1000);
  expect(onPoll).toHaveBeenCalledTimes(1);
  rerender({ active: false });
  vi.advanceTimersByTime(5000);
  expect(onPoll).toHaveBeenCalledTimes(1);
});

test("shouldKickSync fires only on a stalled, enabled reconciler", async () => {
  const { shouldKickSync, SYNC_KICK_COOLDOWN_MS } = await import("./syncPoll");
  const now = 1_000_000_000;
  // Healthy: server-side poller updated recently.
  expect(
    shouldKickSync({ sync_enabled: true, state: "live" }, 0, now),
  ).toBe(false);
  // Stalled (server marks >120s since last pass) — kick it.
  expect(
    shouldKickSync({ sync_enabled: true, state: "stale" }, 0, now),
  ).toBe(true);
  expect(
    shouldKickSync({ sync_enabled: true, state: "dead" }, 0, now),
  ).toBe(true);
  // Sync off: never kick, whatever the state says.
  expect(
    shouldKickSync({ sync_enabled: false, state: "dead" }, 0, now),
  ).toBe(false);
  // Cooldown: a recent kick suppresses another.
  expect(
    shouldKickSync(
      { sync_enabled: true, state: "dead" },
      now - SYNC_KICK_COOLDOWN_MS + 1000,
      now,
    ),
  ).toBe(false);
  // Status not loaded yet.
  expect(shouldKickSync(undefined, 0, now)).toBe(false);
});
