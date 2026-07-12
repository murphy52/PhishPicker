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
