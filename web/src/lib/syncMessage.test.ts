import { renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SYNC_MESSAGE_TYPE, useServiceWorkerSyncMessage } from "./syncMessage";

// jsdom has no serviceWorker; install a minimal EventTarget-backed stub.
function installSW() {
  const target = new EventTarget();
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      addEventListener: target.addEventListener.bind(target),
      removeEventListener: target.removeEventListener.bind(target),
      dispatchEvent: target.dispatchEvent.bind(target),
    },
  });
  return target;
}

afterEach(() => {
  // @ts-expect-error — test cleanup
  delete navigator.serviceWorker;
});

function postMessage(target: EventTarget, data: unknown) {
  const ev = new MessageEvent("message", { data });
  target.dispatchEvent(ev);
}

test("fires onSync for a phish.net sync message", () => {
  const target = installSW();
  const onSync = vi.fn();
  renderHook(() => useServiceWorkerSyncMessage(onSync));
  postMessage(target, { type: SYNC_MESSAGE_TYPE });
  expect(onSync).toHaveBeenCalledTimes(1);
});

test("ignores unrelated messages", () => {
  const target = installSW();
  const onSync = vi.fn();
  renderHook(() => useServiceWorkerSyncMessage(onSync));
  postMessage(target, { type: "something-else" });
  postMessage(target, "not-an-object");
  expect(onSync).not.toHaveBeenCalled();
});

test("removes its listener on unmount", () => {
  const target = installSW();
  const onSync = vi.fn();
  const { unmount } = renderHook(() => useServiceWorkerSyncMessage(onSync));
  unmount();
  postMessage(target, { type: SYNC_MESSAGE_TYPE });
  expect(onSync).not.toHaveBeenCalled();
});

test("is a no-op when the serviceWorker API is absent", () => {
  expect(() =>
    renderHook(() => useServiceWorkerSyncMessage(vi.fn())),
  ).not.toThrow();
});
