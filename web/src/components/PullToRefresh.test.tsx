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
