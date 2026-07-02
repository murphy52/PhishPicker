import {
  buildFeedEvents,
  nextMultiplier,
  reasonLabel,
  type Attribution,
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
