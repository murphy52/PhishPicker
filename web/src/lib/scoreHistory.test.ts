import { describe, expect, it } from "vitest";
import { sortScorecards, type Scorecard } from "./scoreHistory";

const card = (show_date: string, combined: number): Scorecard => ({
  show_id: `${show_date}-${combined}`,
  show_date,
  finalized_at: `${show_date}T12:00:00Z`,
  combined,
  foresight_total: 0,
  live_total: combined,
  ppps: 0,
  max_streak: 0,
});

const rows = [
  card("2026-05-02", 90),
  card("2026-07-07", 155),
  card("2026-04-16", 155), // ties with 07-07 on score
];

describe("sortScorecards", () => {
  it("sorts by date descending", () => {
    const out = sortScorecards(rows, "date", "desc").map((r) => r.show_date);
    expect(out).toEqual(["2026-07-07", "2026-05-02", "2026-04-16"]);
  });

  it("sorts by date ascending", () => {
    const out = sortScorecards(rows, "date", "asc").map((r) => r.show_date);
    expect(out).toEqual(["2026-04-16", "2026-05-02", "2026-07-07"]);
  });

  it("sorts by score descending, newest-first on ties", () => {
    const out = sortScorecards(rows, "score", "desc").map((r) => [
      r.combined,
      r.show_date,
    ]);
    expect(out).toEqual([
      [155, "2026-07-07"],
      [155, "2026-04-16"],
      [90, "2026-05-02"],
    ]);
  });

  it("does not mutate the input array", () => {
    const copy = [...rows];
    sortScorecards(rows, "score", "asc");
    expect(rows).toEqual(copy);
  });
});
