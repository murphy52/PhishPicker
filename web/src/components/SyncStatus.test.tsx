import { render, screen, waitFor } from "@testing-library/react";
import { SyncStatus } from "./SyncStatus";

function mockStatus(state: string, extra: Partial<Record<string, unknown>> = {}) {
  return {
    state,
    sync_enabled: state !== "off",
    last_updated: "2026-04-23T19:05:00Z",
    last_error: null,
    ...extra,
  };
}

function installFetchMock(status: ReturnType<typeof mockStatus>) {
  global.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = typeof url === "string" ? url : url.toString();
    if (init?.method === "POST") {
      return { ok: true, json: async () => ({ started: true }) } as Response;
    }
    if (u.includes("/sync/status")) {
      return { ok: true, json: async () => status } as Response;
    }
    return { ok: true, json: async () => ({}) } as Response;
  }) as unknown as typeof fetch;
}

afterEach(() => {
  vi.restoreAllMocks();
});

test("renders 'off' pill when sync is off", async () => {
  installFetchMock(mockStatus("off"));
  render(<SyncStatus showId={`show-${Math.random()}`} showDate="2026-04-23" />);
  expect(await screen.findByTestId("sync-status")).toHaveTextContent(/off/i);
});

test("renders 'live' pill when sync is live", async () => {
  installFetchMock(mockStatus("live"));
  render(<SyncStatus showId={`show-${Math.random()}`} showDate="2026-04-23" />);
  expect(await screen.findByTestId("sync-status")).toHaveTextContent(/live/i);
});

test("tapping the pill when off POSTs to start", async () => {
  installFetchMock(mockStatus("off"));
  render(<SyncStatus showId={`show-${Math.random()}`} showDate="2026-04-23" />);
  const pill = await screen.findByTestId("sync-status");
  pill.click();
  await waitFor(() => {
    const calls = (global.fetch as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const started = calls.some(
      (c) =>
        typeof c[0] === "string" &&
        (c[0] as string).includes("/sync/start") &&
        (c[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(started).toBe(true);
  });
});

test("tapping the pill when live POSTs to stop", async () => {
  installFetchMock(mockStatus("live"));
  render(<SyncStatus showId={`show-${Math.random()}`} showDate="2026-04-23" />);
  const pill = await screen.findByTestId("sync-status");
  pill.click();
  await waitFor(() => {
    const calls = (global.fetch as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const stopped = calls.some(
      (c) =>
        typeof c[0] === "string" &&
        (c[0] as string).includes("/sync/stop") &&
        (c[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(stopped).toBe(true);
  });
});
