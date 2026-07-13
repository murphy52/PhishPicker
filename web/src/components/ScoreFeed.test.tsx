import { fireEvent, render, screen } from "@testing-library/react";
import type { FeedEvent } from "@/lib/score";
import { ScoreFeed } from "./ScoreFeed";

function event(overrides: Partial<FeedEvent>): FeedEvent {
  return {
    index: 0,
    name: "Tweezer",
    setNumber: "2",
    kind: "live",
    headline: "NEXT-SONG ✓",
    points: 30,
    mult: null,
    sequenceStreak: null,
    beaten: null,
    foreseen: false,
    calledEarly: false,
    corrected: false,
    ...overrides,
  };
}

beforeEach(() => localStorage.clear());

test("empty state", () => {
  render(<ScoreFeed events={[]} />);
  expect(screen.getByText(/Nothing on the board yet/)).toBeInTheDocument();
});

test("renders events with points and the beaten-claim line", () => {
  render(
    <ScoreFeed
      events={[
        event({
          index: 3,
          points: 45,
          mult: 1.5,
          beaten: "beat 🔮 on the board +5",
        }),
      ]}
    />,
  );
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
  expect(screen.getByText(/\(beat 🔮 on the board \+5\)/)).toBeInTheDocument();
  expect(screen.getByText("+45")).toBeInTheDocument();
});

test("bustout row celebrates; miss row stays quiet", () => {
  render(
    <ScoreFeed
      events={[
        event({ index: 1, kind: "bustout", name: "Icculus", points: 0, headline: "BUSTOUT" }),
        event({ index: 0, kind: "miss", name: "Sample", points: 0, headline: "MISSED" }),
      ]}
    />,
  );
  const rows = screen.getAllByTestId("feed-event");
  expect(rows[0]).toHaveAttribute("data-kind", "bustout");
  expect(screen.getByText(/nobody calls those/)).toBeInTheDocument();
  expect(rows[1]).toHaveAttribute("data-kind", "miss");
});

test("exact-sequence combo shows the 🔥 badge and the ×mult", () => {
  render(
    <ScoreFeed
      events={[
        event({
          kind: "foresight",
          headline: "EXACT SLOT",
          points: 120,
          mult: 1.5,
          sequenceStreak: 2,
        }),
      ]}
    />,
  );
  const badge = screen.getByTestId("sequence-badge");
  expect(badge).toHaveTextContent("2 in a row");
  expect(screen.getByText("×1.5")).toBeInTheDocument();
});

test("badges: foreseen, called-early, corrected", () => {
  render(
    <ScoreFeed
      events={[
        event({
          index: 2,
          kind: "foresight",
          foreseen: true,
          calledEarly: true,
          corrected: true,
        }),
      ]}
    />,
  );
  expect(screen.getByTestId("foreseen-badge")).toBeInTheDocument();
  expect(screen.getByTestId("early-badge")).toBeInTheDocument();
  expect(screen.getByTestId("corrected-badge")).toBeInTheDocument();
});

test("coach mark shows on first event, dismisses persistently", () => {
  const { unmount } = render(<ScoreFeed events={[event({})]} />);
  fireEvent.click(screen.getByRole("button", { name: /got it/i }));
  expect(screen.queryByTestId("coach-mark")).not.toBeInTheDocument();
  unmount();
  render(<ScoreFeed events={[event({})]} />);
  expect(screen.queryByTestId("coach-mark")).not.toBeInTheDocument();
});

test("no coach mark with no events", () => {
  render(<ScoreFeed events={[]} />);
  expect(screen.queryByTestId("coach-mark")).not.toBeInTheDocument();
});
