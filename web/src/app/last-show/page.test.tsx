import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SWRConfig } from "swr";
import LastShowPage from "./page";

afterEach(() => vi.restoreAllMocks());

// SWR caches by key globally — without a fresh provider per render, test 2
// gets test 1's response from cache and never calls the new mocked fetch.
function renderIsolated() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <LastShowPage />
    </SWRConfig>,
  );
}

function mockReview(slots: unknown[]) {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      show: {
        show_id: 102,
        show_date: "2026-04-25",
        venue: "Sphere",
        city: "Las Vegas",
        state: "NV",
        run_position: 6,
        run_length: 9,
      },
      slots,
    }),
  })) as unknown as typeof fetch;
}

test("renders setlist grouped by set", async () => {
  mockReview([
    { slot_idx: 1, set_number: "1", position: 1, actual_song_id: 1, actual_song: "Timber", actual_rank: 7 },
    { slot_idx: 2, set_number: "1", position: 2, actual_song_id: 2, actual_song: "Moma Dance", actual_rank: 1 },
    { slot_idx: 3, set_number: "E", position: 1, actual_song_id: 3, actual_song: "Bug", actual_rank: 19 },
  ]);
  renderIsolated();
  await waitFor(() => expect(screen.getByText("Timber")).toBeInTheDocument());
  expect(screen.getByText("Moma Dance")).toBeInTheDocument();
  expect(screen.getByText("Bug")).toBeInTheDocument();
  expect(screen.getByText("SET 1")).toBeInTheDocument();
  expect(screen.getByText("ENCORE")).toBeInTheDocument();
});

test("renders rank pills for each slot", async () => {
  mockReview([
    { slot_idx: 1, set_number: "1", position: 1, actual_song_id: 1, actual_song: "X", actual_rank: 1 },
  ]);
  renderIsolated();
  await waitFor(() => expect(screen.getByTestId("rank-pill")).toHaveTextContent("#1"));
});

test("shows empty state when API returns 404", async () => {
  global.fetch = vi.fn(async () => ({
    ok: false,
    status: 404,
    json: async () => null,
  })) as unknown as typeof fetch;
  renderIsolated();
  await waitFor(() =>
    expect(screen.getByText(/no completed show/i)).toBeInTheDocument(),
  );
});
