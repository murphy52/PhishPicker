import { render, screen } from "@testing-library/react";
import type { PickOutcome } from "@/lib/score";
import { PredictedSetlist } from "./PredictedSetlist";

function outcome(overrides: Partial<PickOutcome> & { set: string; pos: number; name: string; reason: string }): PickOutcome {
  const { set, pos, name, reason, ...rest } = overrides;
  return {
    pick: { set_number: set, position: pos, song_id: pos },
    reason,
    base: 0,
    actual_index: reason === "absent" ? null : 0,
    name,
    ...rest,
  };
}

const OUTCOMES: PickOutcome[] = [
  outcome({ set: "1", pos: 1, name: "Chalk Dust", reason: "opener" }),
  outcome({ set: "1", pos: 2, name: "Reba", reason: "absent" }),
  outcome({ set: "E", pos: 1, name: "Loving Cup", reason: "right_set" }),
];

test("empty state before the bracket freezes", () => {
  render(<PredictedSetlist outcomes={[]} />);
  expect(screen.getByText(/bracket locks when the first song/)).toBeInTheDocument();
});

test("groups picks by set with a hit summary", () => {
  render(<PredictedSetlist outcomes={OUTCOMES} />);
  expect(screen.getAllByTestId("bracket-set")).toHaveLength(2);
  expect(screen.getByText(/2 of 3 picks landed so far/)).toBeInTheDocument();
  expect(screen.getByText("Chalk Dust")).toBeInTheDocument();
  expect(screen.getByText("Reba")).toBeInTheDocument();
});

test("marks absent picks as not-hit and played picks as hit", () => {
  render(<PredictedSetlist outcomes={OUTCOMES} />);
  const picks = screen.getAllByTestId("bracket-pick");
  const byName = Object.fromEntries(
    picks.map((el) => [el.textContent, el.getAttribute("data-hit")]),
  );
  expect(Object.entries(byName).find(([t]) => t?.includes("Chalk Dust"))?.[1]).toBe("true");
  expect(Object.entries(byName).find(([t]) => t?.includes("Reba"))?.[1]).toBe("false");
});

test("final framing drops the 'so far'", () => {
  render(<PredictedSetlist outcomes={OUTCOMES} final />);
  expect(screen.getByText(/2 of 3 picks landed$/)).toBeInTheDocument();
});
