import { render, screen } from "@testing-library/react";
import ScoringPage from "./page";

test("renders the page title", () => {
  render(<ScoringPage />);
  expect(
    screen.getByRole("heading", { name: /how scoring works/i }),
  ).toBeInTheDocument();
});

test("explains both ledgers", () => {
  render(<ScoringPage />);
  expect(screen.getByRole("heading", { name: /foresight/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /live/i })).toBeInTheDocument();
});

test("shows the full foresight point ladder", () => {
  render(<ScoringPage />);
  // 5 / 15 / 80 / 100 — the ordering does the work, magnitudes reward scarcity.
  expect(screen.getByText("+5")).toBeInTheDocument();
  expect(screen.getByText("+15")).toBeInTheDocument();
  expect(screen.getByText("+80")).toBeInTheDocument();
  expect(screen.getByText("+100")).toBeInTheDocument();
});

test("shows the combo multiplier tiers for both the live and foresight combos", () => {
  render(<ScoringPage />);
  // Each ladder (live next-song + foresight exact-sequence) lists ×1/×1.5/×2.
  expect(screen.getAllByText("×1")).toHaveLength(2);
  expect(screen.getAllByText("×1.5")).toHaveLength(2);
  expect(screen.getAllByText("×2")).toHaveLength(2);
});

test("explains best-claim-wins", () => {
  render(<ScoringPage />);
  expect(screen.getByText(/best claim wins/i)).toBeInTheDocument();
});

test("explains PPPS", () => {
  render(<ScoringPage />);
  expect(screen.getByText(/points per predictable song/i)).toBeInTheDocument();
});

test("covers bustouts and the streak reset", () => {
  render(<ScoringPage />);
  expect(screen.getAllByText(/bustout/i).length).toBeGreaterThan(0);
});

test("has a back link", () => {
  render(<ScoringPage />);
  expect(screen.getByRole("link", { name: /back/i })).toBeInTheDocument();
});
