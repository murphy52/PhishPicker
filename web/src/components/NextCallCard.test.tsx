import { render, screen } from "@testing-library/react";
import type { FeedEvent } from "@/lib/score";
import { NextCallCard } from "./NextCallCard";

const call = { name: "Sand", setNumber: "2", position: 3 };

function event(overrides: Partial<FeedEvent>): FeedEvent {
  return {
    index: 1,
    name: "Tweezer",
    setNumber: "2",
    kind: "live",
    headline: "NEXT-SONG ✓",
    points: 45,
    mult: 1.5,
    sequenceStreak: null,
    beaten: null,
    foreseen: false,
    calledEarly: false,
    corrected: false,
    ...overrides,
  };
}

test("renders the pending call face", () => {
  render(<NextCallCard call={call} isOpener={false} />);
  const card = screen.getByTestId("next-call-card");
  expect(card).toHaveAttribute("data-face", "pending");
  expect(screen.getByText("Sand")).toBeInTheDocument();
  expect(screen.getByText(/Set 2 · slot 3/)).toBeInTheDocument();
});

test("frames the pre-show call as the predicted opener", () => {
  render(<NextCallCard call={call} isOpener />);
  expect(screen.getByText(/Predicted opener/)).toBeInTheDocument();
});

test("empty state when no predicted slot remains", () => {
  render(<NextCallCard call={null} isOpener={false} />);
  expect(screen.getByTestId("next-call-card")).toHaveAttribute(
    "data-face",
    "empty",
  );
});

test("a NEW event flips to the hit face with points and multiplier", () => {
  const { rerender } = render(
    <NextCallCard call={call} isOpener={false} lastEvent={event({ index: 1 })} />,
  );
  // First render seeds history — no flash.
  expect(screen.getByTestId("next-call-card")).toHaveAttribute(
    "data-face",
    "pending",
  );
  rerender(
    <NextCallCard
      call={call}
      isOpener={false}
      lastEvent={event({ index: 2, points: 60, mult: 2 })}
    />,
  );
  const card = screen.getByTestId("next-call-card");
  expect(card).toHaveAttribute("data-face", "hit");
  expect(screen.getByText("+60 ×2")).toBeInTheDocument();
});

test("a miss deflates; a bustout celebrates", () => {
  const { rerender } = render(
    <NextCallCard call={call} isOpener={false} lastEvent={event({ index: 1 })} />,
  );
  rerender(
    <NextCallCard
      call={call}
      isOpener={false}
      lastEvent={event({ index: 2, kind: "miss", points: 0, mult: null })}
    />,
  );
  expect(screen.getByTestId("next-call-card")).toHaveAttribute(
    "data-face",
    "miss",
  );
  rerender(
    <NextCallCard
      call={call}
      isOpener={false}
      lastEvent={event({
        index: 3,
        kind: "bustout",
        name: "Icculus",
        points: 0,
        mult: null,
      })}
    />,
  );
  expect(screen.getByTestId("next-call-card")).toHaveAttribute(
    "data-face",
    "bustout",
  );
  expect(screen.getByText(/nobody saw it coming/)).toBeInTheDocument();
});

test("a foreseen bank flips indigo, not amber", () => {
  const { rerender } = render(
    <NextCallCard call={call} isOpener={false} lastEvent={event({ index: 1 })} />,
  );
  rerender(
    <NextCallCard
      call={call}
      isOpener={false}
      lastEvent={event({
        index: 2,
        kind: "foresight",
        foreseen: true,
        points: 40,
        mult: null,
      })}
    />,
  );
  expect(screen.getByText(/Foreseen/)).toBeInTheDocument();
  expect(screen.getByTestId("next-call-card")).toHaveAttribute(
    "data-face",
    "hit",
  );
});
