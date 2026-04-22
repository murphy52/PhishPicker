import {
  applyPendingMutation,
  type PendingMutation,
  type PreviewSlot,
} from "./preview";

function predicted(slotIdx: number, set: string, pos: number): PreviewSlot {
  return {
    slot_idx: slotIdx,
    set_number: set,
    position: pos,
    state: "predicted",
    top_k: [{ song_id: 99, name: "Nope", probability: 0.1, score: 1, rank: 1 }],
  };
}

function entered(slotIdx: number, set: string, pos: number, song: {
  song_id: number;
  name: string;
}): PreviewSlot {
  return {
    slot_idx: slotIdx,
    set_number: set,
    position: pos,
    state: "entered",
    entered_song: song,
  };
}

test("null pending returns the slots unchanged", () => {
  const slots = [predicted(1, "1", 1)];
  expect(applyPendingMutation(slots, null)).toBe(slots);
});

test("add: replaces first predicted slot in matching set with pending=adding", () => {
  const slots = [
    entered(1, "1", 1, { song_id: 100, name: "Monsters" }),
    predicted(2, "1", 2),
    predicted(3, "1", 3),
  ];
  const pending: PendingMutation = {
    kind: "add",
    song: { song_id: 42, name: "Tweezer" },
    setNumber: "1",
  };
  const out = applyPendingMutation(slots, pending);
  expect(out[1].state).toBe("entered");
  expect(out[1].pending).toBe("adding");
  expect(out[1].entered_song).toEqual({ song_id: 42, name: "Tweezer" });
  // Other slots untouched
  expect(out[0]).toBe(slots[0]);
  expect(out[2]).toBe(slots[2]);
});

test("add: targets the set matching pending.setNumber even if Set 1 still has predicted slots", () => {
  const slots = [
    predicted(1, "1", 1),
    predicted(2, "2", 1),
  ];
  const out = applyPendingMutation(slots, {
    kind: "add",
    song: { song_id: 7, name: "Reba" },
    setNumber: "2",
  });
  expect(out[0].state).toBe("predicted"); // set 1 untouched
  expect(out[1].state).toBe("entered");
  expect(out[1].pending).toBe("adding");
});

test("undo: marks last matching entered slot as pending=removing", () => {
  const slots = [
    entered(1, "1", 1, { song_id: 100, name: "Monsters" }),
    entered(2, "1", 2, { song_id: 200, name: "Wilson" }),
    predicted(3, "1", 3),
  ];
  const out = applyPendingMutation(slots, { kind: "undo", songId: 200 });
  expect(out[1].pending).toBe("removing");
  expect(out[1].state).toBe("entered"); // still entered, just marked
  expect(out[0].pending).toBeUndefined();
});

test("undo: picks the LAST matching slot when the same song is in multiple slots", () => {
  const slots = [
    entered(1, "1", 1, { song_id: 100, name: "Monsters" }),
    entered(2, "2", 1, { song_id: 100, name: "Monsters" }),
  ];
  const out = applyPendingMutation(slots, { kind: "undo", songId: 100 });
  expect(out[0].pending).toBeUndefined();
  expect(out[1].pending).toBe("removing");
});
