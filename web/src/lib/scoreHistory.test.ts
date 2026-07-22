import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  sortScorecards,
  useSortPreference,
  versusSummary,
  type Scorecard,
} from "./scoreHistory";

const card = (show_date: string, combined: number): Scorecard => ({
  show_id: `${show_date}-${combined}`,
  show_date,
  finalized_at: `${show_date}T12:00:00Z`,
  combined,
  foresight_total: 0,
  live_total: combined,
  ppps: 0,
  max_streak: 0,
  versus_phish: null,
  versus_picker: null,
  versus_leader: null,
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

describe("useSortPreference", () => {
  afterEach(() => localStorage.clear());

  it("defaults to date descending", () => {
    const { result } = renderHook(() => useSortPreference());
    expect(result.current[0]).toEqual({ key: "date", dir: "desc" });
  });

  it("toggle switches column (desc), then flips direction on re-select", () => {
    const { result } = renderHook(() => useSortPreference());
    act(() => result.current[1]("score"));
    expect(result.current[0]).toEqual({ key: "score", dir: "desc" });
    act(() => result.current[1]("score"));
    expect(result.current[0]).toEqual({ key: "score", dir: "asc" });
  });

  it("persists the choice to localStorage", () => {
    const { result } = renderHook(() => useSortPreference());
    act(() => result.current[1]("score")); // new column -> desc
    expect(JSON.parse(localStorage.getItem("phishpicker:history_sort")!)).toEqual(
      { key: "score", dir: "desc" },
    );
  });

  it("hydrates a stored preference on mount (survives refresh/navigation)", () => {
    localStorage.setItem(
      "phishpicker:history_sort",
      JSON.stringify({ key: "score", dir: "asc" }),
    );
    const { result } = renderHook(() => useSortPreference());
    expect(result.current[0]).toEqual({ key: "score", dir: "asc" });
  });

  it("ignores a corrupt stored value and keeps the default", () => {
    localStorage.setItem("phishpicker:history_sort", "{not json");
    const { result } = renderHook(() => useSortPreference());
    expect(result.current[0]).toEqual({ key: "date", dir: "desc" });
  });

  it("ignores a structurally invalid stored value", () => {
    localStorage.setItem(
      "phishpicker:history_sort",
      JSON.stringify({ key: "bogus", dir: "sideways" }),
    );
    const { result } = renderHook(() => useSortPreference());
    expect(result.current[0]).toEqual({ key: "date", dir: "desc" });
  });
});

describe("versusSummary", () => {
  const vs = (
    phish: number | null,
    picker: number | null,
    leader: Scorecard["versus_leader"],
  ): Scorecard => ({
    ...card("2026-07-21", 143),
    versus_phish: phish,
    versus_picker: picker,
    versus_leader: leader,
  });

  it("returns null for shows without a vs-game (pre-feature or never frozen)", () => {
    expect(versusSummary(vs(null, null, null))).toBeNull();
  });

  it("names Phish the winner", () => {
    expect(versusSummary(vs(41, 38, "phish"))).toEqual({
      winner: "phish",
      label: "Phish wins 41–38",
    });
  });

  it("names PhishPicker the winner", () => {
    expect(versusSummary(vs(20, 46, "picker"))).toEqual({
      winner: "picker",
      label: "Picker wins 46–20",
    });
  });

  it("calls a tie", () => {
    expect(versusSummary(vs(33, 33, "tie"))).toEqual({
      winner: "tie",
      label: "Tie 33–33",
    });
  });
});
