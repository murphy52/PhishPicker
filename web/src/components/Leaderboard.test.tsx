import { render, screen } from "@testing-library/react";
import { Leaderboard } from "./Leaderboard";

const candidates = [
  { song_id: 1, name: "Chalk Dust Torture", probability: 0.3, score: 5 },
  { song_id: 2, name: "Tweezer", probability: 0.1, score: 2 },
  { song_id: 3, name: "Wilson", probability: 0.05, score: 1 },
];

test("renders each candidate as a list item", () => {
  render(<Leaderboard candidates={candidates} />);
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
});

test("shows candidate names", () => {
  render(<Leaderboard candidates={candidates} />);
  expect(screen.getByText("Chalk Dust Torture")).toBeInTheDocument();
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
});

test("first item is the highest-probability candidate", () => {
  render(<Leaderboard candidates={candidates} />);
  const items = screen.getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("Chalk Dust Torture");
});

test("displays probability as percentage", () => {
  render(<Leaderboard candidates={candidates} />);
  expect(screen.getByText("30%")).toBeInTheDocument();
});

test("renders empty list without crashing", () => {
  render(<Leaderboard candidates={[]} />);
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});
