import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AboutMetrics, type Metrics } from "./AboutMetrics";

const sample: Metrics = {
  trained_at: "2026-04-17T12:34:56Z",
  cutoff_date: "2026-04-17",
  model_version: "0.2.0-lightgbm",
  n_shows_trained_on: 1843,
  n_slots: 389,
  holdout_shows: 20,
  top1: 0.11,
  top5: 0.31,
  top20: 0.62,
  mrr: 0.18,
  top1_ci: [0.08, 0.14],
  top5_ci: [0.27, 0.35],
  top20_ci: [0.58, 0.66],
  mrr_ci: [0.16, 0.21],
  by_slot: {
    "1": { top1: 0.22, top5: 0.58, mrr: 0.35, n: 20 },
    "2": { top1: 0.06, top5: 0.20, mrr: 0.11, n: 20 },
  },
  baselines: {
    random: { top1: 0.001, top5: 0.005, top20: 0.02, mrr: 0.005 },
    frequency: { top1: 0.05, top5: 0.19, top20: 0.45, mrr: 0.1 },
    heuristic: { top1: 0.07, top5: 0.22, top20: 0.5, mrr: 0.13 },
  },
  feature_columns: ["total_plays_ever", "plays_last_12mo"],
  ship_gate_passed: true,
};

describe("AboutMetrics", () => {
  it("renders headline metrics with CIs", () => {
    render(<AboutMetrics metrics={sample} />);
    // Same labels/values appear in multiple sections; assert multi-presence.
    expect(screen.getAllByText(/Top-1/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/11\.0%/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/8\.0%–14\.0%/)).toBeInTheDocument();
  });

  it("renders baseline comparison table", () => {
    render(<AboutMetrics metrics={sample} />);
    expect(screen.getByText(/frequency/i)).toBeInTheDocument();
    expect(screen.getByText(/heuristic/i)).toBeInTheDocument();
    expect(screen.getByText(/random/i)).toBeInTheDocument();
  });

  it("renders per-slot breakdown when present", () => {
    render(<AboutMetrics metrics={sample} />);
    expect(screen.getByText(/Slot 1/)).toBeInTheDocument();
    expect(screen.getByText(/Slot 2/)).toBeInTheDocument();
  });

  it("reports model version and training date", () => {
    render(<AboutMetrics metrics={sample} />);
    expect(screen.getByText(/0\.2\.0-lightgbm/)).toBeInTheDocument();
    expect(screen.getByText(/1843 shows/)).toBeInTheDocument();
  });

  it("flags failed ship-gate distinctly", () => {
    render(<AboutMetrics metrics={{ ...sample, ship_gate_passed: false }} />);
    expect(screen.getByText(/ship gate failed/i)).toBeInTheDocument();
  });
});
