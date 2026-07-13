import { render, screen } from "@testing-library/react";
import type { Attribution, FinalizeResponse } from "@/lib/score";
import { RecapView } from "./RecapView";

function att(overrides: Partial<Attribution>): Attribution {
  return {
    index: 0,
    song_id: 1,
    set_number: "1",
    position: 1,
    ledger: null,
    base: 0,
    reason: null,
    beaten_claim: null,
    called_right: null,
    streak: 0,
    mult: null,
    fs_streak: 0,
    fs_mult: null,
    final: 0,
    called_early: false,
    bustout: false,
    missed: false,
    name: "Song",
    ...overrides,
  };
}

function fixture(overrides?: {
  is_best?: boolean;
  shows_scored?: number;
}): FinalizeResponse {
  return {
    scorecard: {
      show_id: "abc",
      show_date: "2026-07-07",
      finalized_at: "2026-07-08T04:00:00Z",
      combined: 135,
      foresight_total: 60,
      live_total: 75,
      ppps: 33.8,
      max_streak: 2,
    },
    context: {
      shows_scored: overrides?.shows_scored ?? 3,
      best_total: 200,
      best_ppps: 50,
      rank_by_total: 2,
      is_best: overrides?.is_best ?? false,
    },
    result: {
      attributions: [
        att({ index: 0, name: "Buried Alive", ledger: "foresight", reason: "opener", final: 60 }),
        att({ index: 1, name: "Tweezer", ledger: "live", reason: "next_song", final: 45, streak: 2 }),
        att({ index: 2, name: "Icculus", bustout: true }),
        att({ index: 3, name: "Sample in a Jar", missed: true }),
      ],
      totals: { foresight_total: 60, live_total: 75, combined: 135, ppps: 33.8, hit_counts: {} },
      pick_outcomes: [],
      model_sha: "abc",
      frozen: true,
    },
  };
}

test("renders total, split, stats, and all three sections", () => {
  render(<RecapView data={fixture()} />);
  expect(screen.getByTestId("recap-total")).toHaveTextContent("135");
  expect(screen.getByText("🔮 60")).toBeInTheDocument();
  expect(screen.getByText("⚡ 75")).toBeInTheDocument();
  expect(screen.getByText("2 in a row")).toBeInTheDocument();
  expect(screen.getByText("Buried Alive")).toBeInTheDocument();
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
  // Both the bustout and the plain miss land in "songs that beat the app"
  const beat = screen.getByTestId("recap-section-beat");
  expect(beat).toHaveTextContent("Icculus");
  expect(beat).toHaveTextContent("Sample in a Jar");
});

test("ranked line when not the best", () => {
  render(<RecapView data={fixture({ is_best: false })} />);
  expect(screen.getByTestId("rank-line")).toHaveTextContent("#2 of 3 shows");
  expect(screen.queryByTestId("best-badge")).not.toBeInTheDocument();
});

test("best-yet badge", () => {
  render(<RecapView data={fixture({ is_best: true })} />);
  expect(screen.getByTestId("best-badge")).toBeInTheDocument();
});

test("no rank context on the first scored show", () => {
  render(<RecapView data={fixture({ shows_scored: 1 })} />);
  expect(screen.queryByTestId("rank-line")).not.toBeInTheDocument();
  expect(screen.queryByTestId("best-badge")).not.toBeInTheDocument();
});
