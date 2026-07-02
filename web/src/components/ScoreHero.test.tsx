import { render, screen } from "@testing-library/react";
import { ScoreHero } from "./ScoreHero";

const totals = {
  foresight_total: 120,
  live_total: 195,
  combined: 315,
  ppps: 45,
  hit_counts: {},
};

test("renders combined total and the ledger split", () => {
  render(<ScoreHero totals={totals} frozen />);
  expect(screen.getByTestId("hero-total")).toHaveTextContent("315");
  expect(screen.getByTestId("foresight-total")).toHaveTextContent("120");
  expect(screen.getByTestId("live-total")).toHaveTextContent("195");
});

test("shows the lock hint until the bracket freezes", () => {
  render(<ScoreHero totals={{ ...totals, combined: 0 }} frozen={false} />);
  expect(screen.getByText(/locks at the first song/)).toBeInTheDocument();
});

test("hides the lock hint once frozen", () => {
  render(<ScoreHero totals={totals} frozen />);
  expect(screen.queryByText(/locks at the first song/)).not.toBeInTheDocument();
});
