import {
  buildFeedEvents,
  groupBracketBySet,
  nextMultiplier,
  reasonLabel,
  recapBreakdown,
  type Attribution,
  type PickOutcome,
} from "./score";

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
    final: 0,
    called_early: false,
    bustout: false,
    missed: false,
    name: "Song",
    ...overrides,
  };
}

test("newest attribution first", () => {
  const events = buildFeedEvents([
    att({ index: 0, name: "Chalk Dust" }),
    att({ index: 1, name: "Tweezer" }),
  ]);
  expect(events.map((e) => e.name)).toEqual(["Tweezer", "Chalk Dust"]);
});

test("live hit event carries points, multiplier, and the beaten claim", () => {
  const [e] = buildFeedEvents([
    att({
      index: 1,
      name: "Tweezer",
      ledger: "live",
      reason: "next_song",
      base: 30,
      mult: 1.5,
      final: 45,
      streak: 2,
      called_right: true,
      beaten_claim: { ledger: "foresight", reason: "somewhere", base: 5 },
    }),
  ]);
  expect(e.kind).toBe("live");
  expect(e.points).toBe(45);
  expect(e.mult).toBe(1.5);
  expect(e.beaten).toBe("beat 🔮 on the board +5");
});

test("foresight opener event", () => {
  const [e] = buildFeedEvents([
    att({
      name: "Chalk Dust",
      ledger: "foresight",
      reason: "opener",
      base: 60,
      final: 60,
    }),
  ]);
  expect(e.kind).toBe("foresight");
  expect(e.headline).toBe("OPENER NAILED");
  expect(e.points).toBe(60);
  expect(e.beaten).toBeNull();
});

test("foreseen beat: foresight bank on a correct call", () => {
  const [e] = buildFeedEvents([
    att({
      index: 2,
      ledger: "foresight",
      reason: "exact",
      final: 40,
      called_right: true,
    }),
  ]);
  expect(e.foreseen).toBe(true);
});

test("bustout celebrates, miss stays quiet", () => {
  const events = buildFeedEvents([
    att({ index: 0, name: "Icculus", bustout: true }),
    att({ index: 1, name: "Sample", missed: true }),
  ]);
  expect(events[1].kind).toBe("bustout");
  expect(events[0].kind).toBe("miss");
});

test("called_early flag surfaces on the event", () => {
  const [e] = buildFeedEvents([att({ called_early: true, missed: true })]);
  expect(e.calledEarly).toBe(true);
});

test("correction detected against previous attributions", () => {
  const prev = [att({ index: 0, song_id: 10, name: "Sample" })];
  const events = buildFeedEvents(
    [att({ index: 0, song_id: 99, name: "Fee" })],
    prev,
  );
  expect(events[0].corrected).toBe(true);
});

test("no correction on identical or brand-new rows", () => {
  const prev = [att({ index: 0, song_id: 10 })];
  const events = buildFeedEvents(
    [att({ index: 0, song_id: 10 }), att({ index: 1, song_id: 11 })],
    prev,
  );
  expect(events.every((e) => !e.corrected)).toBe(true);
});

test("recapBreakdown splits ledgers and finds the hottest run", () => {
  const result = {
    attributions: [
      att({ index: 0, ledger: "foresight", final: 60, streak: 0 }),
      att({ index: 1, ledger: "live", final: 30, streak: 1 }),
      att({ index: 2, ledger: "live", final: 45, streak: 2 }),
      att({ index: 3, missed: true, streak: 0 }),
      att({ index: 4, bustout: true, streak: 0 }),
    ],
    totals: {
      foresight_total: 60,
      live_total: 75,
      combined: 135,
      ppps: 33.75,
      hit_counts: {},
    },
    pick_outcomes: [],
    model_sha: null,
    frozen: true,
  };
  const recap = recapBreakdown(result);
  expect(recap.foresight.map((a) => a.index)).toEqual([0]);
  expect(recap.live.map((a) => a.index)).toEqual([1, 2]);
  expect(recap.beatTheApp.map((a) => a.index)).toEqual([3, 4]);
  expect(recap.maxStreak).toBe(2);
});

test("groupBracketBySet orders sets and positions, tags outcomes", () => {
  const outcomes: PickOutcome[] = [
    { pick: { set_number: "E", position: 1, song_id: 5 }, reason: "opener", base: 60, actual_index: 8, name: "Tweeprise" },
    { pick: { set_number: "1", position: 2, song_id: 2 }, reason: "absent", base: 0, actual_index: null, name: "Reba" },
    { pick: { set_number: "1", position: 1, song_id: 1 }, reason: "opener", base: 60, actual_index: 0, name: "Chalk Dust" },
  ];
  const groups = groupBracketBySet(outcomes);
  expect(groups.map((g) => g.label)).toEqual(["Set 1", "Encore"]);
  expect(groups[0].picks.map((p) => p.name)).toEqual(["Chalk Dust", "Reba"]);
  expect(groups[0].picks[0].hit).toBe(true); // played, banked points
  expect(groups[0].picks[1].hit).toBe(false); // absent
});

test("groupBracketBySet handles multi-encore labels", () => {
  const outcomes: PickOutcome[] = [
    { pick: { set_number: "E2", position: 1, song_id: 9 }, reason: "somewhere", base: 5, actual_index: 12, name: "Tube" },
  ];
  expect(groupBracketBySet(outcomes)[0].label).toBe("Encore 2");
});

test("nextMultiplier ladder", () => {
  expect(nextMultiplier(0)).toBe(1);
  expect(nextMultiplier(1)).toBe(1.5);
  expect(nextMultiplier(2)).toBe(2);
  expect(nextMultiplier(7)).toBe(2);
});

test("reason labels", () => {
  expect(reasonLabel("opener")).toBe("OPENER NAILED");
  expect(reasonLabel("exact")).toBe("EXACT SLOT");
  expect(reasonLabel("right_set")).toBe("RIGHT SET");
  expect(reasonLabel("somewhere")).toBe("ON THE BOARD");
  expect(reasonLabel("next_song")).toBe("NEXT-SONG ✓");
});
