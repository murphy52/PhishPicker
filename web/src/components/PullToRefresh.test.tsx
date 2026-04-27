import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { PullToRefresh } from "./PullToRefresh";

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
});

function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
}

function pullBy(el: Element, deltaY: number) {
  fireEvent.touchStart(el, { touches: [{ clientY: 100 }] });
  fireEvent.touchMove(el, { touches: [{ clientY: 100 + deltaY }] });
  fireEvent.touchEnd(el);
}

test("fires onRefresh when pulled past the threshold", async () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  pullBy(screen.getByTestId("content").parentElement!, 120);
  await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
});

test("does NOT fire onRefresh when pull is below threshold", async () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  pullBy(screen.getByTestId("content").parentElement!, 30);
  // Wait a tick so any pending microtask would have fired.
  await new Promise((r) => setTimeout(r, 0));
  expect(onRefresh).not.toHaveBeenCalled();
});

test("ignores pulls when the page is scrolled below the top", async () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  setScrollY(200);
  pullBy(screen.getByTestId("content").parentElement!, 200);
  await new Promise((r) => setTimeout(r, 0));
  expect(onRefresh).not.toHaveBeenCalled();
});

test("ignores re-pulls while a refresh is already in flight", async () => {
  let resolveFirst!: () => void;
  const onRefresh = vi
    .fn()
    .mockImplementationOnce(() => new Promise<void>((r) => { resolveFirst = r; }))
    .mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  const wrapper = screen.getByTestId("content").parentElement!;
  pullBy(wrapper, 120);
  await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  // Second pull while first is still pending — must not fire.
  pullBy(wrapper, 120);
  await new Promise((r) => setTimeout(r, 0));
  expect(onRefresh).toHaveBeenCalledTimes(1);
  // Resolve the first; another pull is now allowed.
  await act(async () => {
    resolveFirst();
    await new Promise((r) => setTimeout(r, 0));
  });
  pullBy(wrapper, 120);
  await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(2));
});

test("upward pulls (negative deltaY) do not fire onRefresh", async () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  pullBy(screen.getByTestId("content").parentElement!, -150);
  await new Promise((r) => setTimeout(r, 0));
  expect(onRefresh).not.toHaveBeenCalled();
});

test("damping makes the indicator move less than the finger past the free zone", () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  const wrapper = screen.getByTestId("content").parentElement!;
  // Past the free zone, each px of finger contributes less than 1px to
  // the indicator. Raw delta=120 should yield ~90px, not 120px.
  fireEvent.touchStart(wrapper, { touches: [{ clientY: 100 }] });
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 220 }] }); // raw delta 120
  const indicator = screen.getByTestId("ptr-indicator");
  const height = parseInt(indicator.style.height, 10);
  // Strictly less than raw delta — proves damping is applied.
  expect(height).toBeLessThan(120);
  // And past the free zone (60), so it has begun damping (not 0).
  expect(height).toBeGreaterThan(60);
  fireEvent.touchEnd(wrapper);
});

test("free-zone movement is 1:1 with the finger", () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  const wrapper = screen.getByTestId("content").parentElement!;
  fireEvent.touchStart(wrapper, { touches: [{ clientY: 100 }] });
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 140 }] }); // raw delta 40
  const height = parseInt(screen.getByTestId("ptr-indicator").style.height, 10);
  expect(height).toBe(40);
  fireEvent.touchEnd(wrapper);
});

test("fires a haptic click when the indicator crosses the trigger threshold", () => {
  const vibrate = vi.fn();
  Object.defineProperty(navigator, "vibrate", {
    configurable: true,
    value: vibrate,
  });
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  const wrapper = screen.getByTestId("content").parentElement!;
  fireEvent.touchStart(wrapper, { touches: [{ clientY: 100 }] });
  // First move stays inside the free zone — no haptic yet.
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 130 }] });
  expect(vibrate).not.toHaveBeenCalled();
  // Cross the threshold — haptic should fire exactly once.
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 320 }] });
  expect(vibrate).toHaveBeenCalledTimes(1);
  // Continuing to pull past threshold doesn't re-fire.
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 400 }] });
  expect(vibrate).toHaveBeenCalledTimes(1);
  fireEvent.touchEnd(wrapper);
});

test("haptic re-fires when threshold is crossed again after retreating", () => {
  const vibrate = vi.fn();
  Object.defineProperty(navigator, "vibrate", {
    configurable: true,
    value: vibrate,
  });
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  render(
    <PullToRefresh onRefresh={onRefresh}>
      <div data-testid="content">hello</div>
    </PullToRefresh>,
  );
  const wrapper = screen.getByTestId("content").parentElement!;
  fireEvent.touchStart(wrapper, { touches: [{ clientY: 100 }] });
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 320 }] }); // cross
  expect(vibrate).toHaveBeenCalledTimes(1);
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 130 }] }); // retreat
  fireEvent.touchMove(wrapper, { touches: [{ clientY: 320 }] }); // cross again
  expect(vibrate).toHaveBeenCalledTimes(2);
  fireEvent.touchEnd(wrapper);
});
