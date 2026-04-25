# Hit-rank Indicator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show each entered song's rank in the model's retroactive top-10 prediction, rendered right-aligned on the slot row in `/upcoming`.

**Architecture:** Backend computes `hit_rank` for each entered slot by calling `predict_next_stateless` with prior entered slots as context, then finding the entered song's 1-based index (null if outside top-10). The frontend reads `hit_rank` from `/preview` and renders a target icon (rank 1), a `#N` chip (rank 2–10), or an em-dash (null).

**Tech Stack:** FastAPI + SQLite on the backend (`api/`); Next.js + Vitest + React Testing Library on the frontend (`web/`).

**Design doc:** `docs/plans/2026-04-24-hit-rank-indicator-design.md`

---

## Preflight

Run from project root:

```bash
cd /Users/David/phishpicker
git pull
```

Expected: clean working tree, commit `6b60b76` (design doc) in history.

---

### Task 1: Backend — extract `_compute_hit_rank` helper

**Files:**
- Modify: `api/src/phishpicker/live_preview.py` (add module-level helper near the top of the file, above `build_preview`)
- Test: `api/tests/test_live_preview.py` (append new test)

The helper wraps `predict_next_stateless` to return the 1-based rank of a target song in the top-10, or `None` if absent.

**Step 1: Write the failing unit test**

Append to `api/tests/test_live_preview.py`:

```python
def test_compute_hit_rank_returns_rank_when_song_in_top_n(seeded_client, live_show_id):
    """Unit-level smoke test — entered song shows up at rank 1 when it's the top
    candidate given an empty prior context."""
    from phishpicker.db.connection import open_read_db
    from phishpicker.live_preview import _compute_hit_rank
    from phishpicker.model.scorer import HeuristicScorer

    # Seed-provided song ids are small — pick a known one from fixtures.
    with open_read_db() as read_conn:
        # With no prior context, every seed song scores equally; the returned
        # rank must be 1..10 or None, never a non-int.
        rank = _compute_hit_rank(
            read_conn=read_conn,
            played_songs=[],
            target_song_id=100,
            current_set="1",
            show_date="2026-04-23",
            venue_id=1,
            prev_trans_mark=",",
            prev_set_number=None,
            scorer=HeuristicScorer(),
            song_ids_cache=None,
            song_names_cache=None,
            stats_cache=None,
            ext_cache=None,
            bigram_cache=None,
        )
    assert rank is None or (1 <= rank <= 10)


def test_compute_hit_rank_returns_none_for_unknown_song(seeded_client, live_show_id):
    from phishpicker.db.connection import open_read_db
    from phishpicker.live_preview import _compute_hit_rank
    from phishpicker.model.scorer import HeuristicScorer

    with open_read_db() as read_conn:
        rank = _compute_hit_rank(
            read_conn=read_conn,
            played_songs=[],
            target_song_id=9_999_999,  # definitely not in fixtures
            current_set="1",
            show_date="2026-04-23",
            venue_id=1,
            prev_trans_mark=",",
            prev_set_number=None,
            scorer=HeuristicScorer(),
            song_ids_cache=None,
            song_names_cache=None,
            stats_cache=None,
            ext_cache=None,
            bigram_cache=None,
        )
    assert rank is None
```

Note: import path `phishpicker.db.connection.open_read_db` — if that name differs in the codebase, grep first: `grep -rn "def open_read_db\|def open_db" api/src/phishpicker/db/`. Use whatever the test harness uses to obtain a read connection (the integration tests may hand you a `read_conn` fixture — prefer that).

**Step 2: Verify it fails**

Run: `cd api && uv run pytest tests/test_live_preview.py::test_compute_hit_rank_returns_rank_when_song_in_top_n -xvs`

Expected: `ImportError: cannot import name '_compute_hit_rank'`.

**Step 3: Implement the helper**

In `api/src/phishpicker/live_preview.py`, above `build_preview`, add:

```python
def _compute_hit_rank(
    *,
    read_conn,
    played_songs: list[int],
    target_song_id: int,
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str,
    prev_set_number: str | None,
    scorer,
    song_ids_cache,
    song_names_cache,
    stats_cache,
    ext_cache,
    bigram_cache,
) -> int | None:
    cands = predict_next_stateless(
        read_conn=read_conn,
        played_songs=played_songs,
        current_set=current_set,
        show_date=show_date,
        venue_id=venue_id,
        prev_trans_mark=prev_trans_mark,
        prev_set_number=prev_set_number,
        top_n=10,
        scorer=scorer,
        song_ids_cache=song_ids_cache,
        song_names_cache=song_names_cache,
        stats_cache=stats_cache,
        ext_cache=ext_cache,
        bigram_cache=bigram_cache,
    )
    for i, c in enumerate(cands):
        if c["song_id"] == target_song_id:
            return i + 1
    return None
```

**Step 4: Verify the test passes**

Run: `cd api && uv run pytest tests/test_live_preview.py::test_compute_hit_rank_returns_rank_when_song_in_top_n tests/test_live_preview.py::test_compute_hit_rank_returns_none_for_unknown_song -xvs`

Expected: both PASS.

**Step 5: Commit**

```bash
git add api/src/phishpicker/live_preview.py api/tests/test_live_preview.py
git commit -m "feat(api): add _compute_hit_rank helper

Wraps predict_next_stateless, returns 1-based rank in top-10 or None.
Prep for hit_rank field on entered preview slots.

Relates to #6

🤖 assist"
```

---

### Task 2: Backend — emit `hit_rank` from `build_preview`

**Files:**
- Modify: `api/src/phishpicker/live_preview.py` (the main loop in `build_preview`)
- Test: `api/tests/test_live_preview.py` (append)

The loop must (a) rebuild `virtual_played` from scratch as it iterates, (b) compute `hit_rank` for each entered slot before appending, (c) include `hit_rank` on the returned entered-slot dict.

**Step 1: Write the failing integration test**

Append to `api/tests/test_live_preview.py`:

```python
def test_preview_includes_hit_rank_on_entered_slots(seeded_client, live_show_id):
    # Enter a song so we have an entered slot whose hit_rank can be computed.
    r = seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    assert r.status_code == 200

    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    entered = [s for s in slots if s["state"] == "entered"]
    assert entered, "expected one entered slot"
    s = entered[0]
    assert "hit_rank" in s
    # hit_rank is either a 1..10 int or None — both are valid outcomes.
    assert s["hit_rank"] is None or (1 <= s["hit_rank"] <= 10)


def test_preview_predicted_slots_have_no_hit_rank(seeded_client, live_show_id):
    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    predicted = [s for s in slots if s["state"] == "predicted"]
    for s in predicted:
        # Absent key is fine; explicit null is fine; a number is not.
        assert s.get("hit_rank") is None
```

**Step 2: Verify the test fails**

Run: `cd api && uv run pytest tests/test_live_preview.py::test_preview_includes_hit_rank_on_entered_slots -xvs`

Expected: `KeyError: 'hit_rank'` or `AssertionError: "hit_rank" not in s`.

**Step 3: Modify `build_preview` — track trans_mark per entered slot**

The loop currently uses `played_rows[-1]["trans_mark"]` to seed `prev_trans_mark` before the first predicted slot. We need per-entered-slot trans_mark to update context as we iterate.

In `api/src/phishpicker/live_preview.py`, lines 67-80, change how `entered_by_pos` is built so each value carries `trans_mark` too:

```python
entered_by_pos: dict[tuple[str, int], dict] = {}
per_set_seen: dict[str, int] = {}
for r in played_rows:
    per_set_seen[r["set_number"]] = per_set_seen.get(r["set_number"], 0) + 1
    entered_by_pos[(r["set_number"], per_set_seen[r["set_number"]])] = {
        "song_id": r["song_id"],
        "name": song_names.get(r["song_id"], f"#{r['song_id']}"),
        "trans_mark": r["trans_mark"],
    }
```

Remove the now-unused `virtual_played`, `prev_trans_mark`, `prev_set_number` initialization from `played_rows[-1]` — they'll be rebuilt inside the loop. Replace with:

```python
virtual_played: list[int] = []
prev_trans_mark = ","
prev_set_number: str | None = None
```

**Step 4: Modify the loop to compute `hit_rank` and rebuild context**

Replace the `if entered:` branch (lines 111-122) with:

```python
entered = entered_by_pos.get((set_number, pos))
if entered:
    hit_rank = _compute_hit_rank(
        read_conn=read_conn,
        played_songs=virtual_played,
        target_song_id=entered["song_id"],
        current_set=set_number,
        show_date=show_date,
        venue_id=venue_id,
        prev_trans_mark=prev_trans_mark,
        prev_set_number=prev_set_number,
        scorer=scorer,
        song_ids_cache=song_ids,
        song_names_cache=song_names,
        stats_cache=stats_cache,
        ext_cache=ext_cache,
        bigram_cache=bigram_cache,
    )
    slots.append(
        {
            "slot_idx": slot_idx,
            "set_number": set_number,
            "position": pos,
            "state": "entered",
            "entered_song": {
                "song_id": entered["song_id"],
                "name": entered["name"],
            },
            "hit_rank": hit_rank,
        }
    )
    virtual_played = virtual_played + [entered["song_id"]]
    prev_trans_mark = entered["trans_mark"]
    prev_set_number = set_number
    continue
```

Notes:
- `entered_song` no longer contains `trans_mark` — strip it there to preserve the public response shape (`EnteredSong` on the client has only `song_id`, `name`).
- The predicted branch below is unchanged — it keeps appending `cands[0]["song_id"]` to `virtual_played`. Behavior for predicted slots is identical to before, because at the first predicted slot `virtual_played` now equals the full prior-entered list (same as the old one-shot initialization).

**Step 5: Run the new tests**

Run: `cd api && uv run pytest tests/test_live_preview.py -xvs`

Expected: all existing preview tests still pass; the two new tests pass.

**Step 6: Run the full backend suite**

Run: `cd api && uv run pytest -x`

Expected: no regressions.

**Step 7: Commit**

```bash
git add api/src/phishpicker/live_preview.py api/tests/test_live_preview.py
git commit -m "feat(api): emit hit_rank on entered preview slots

Retroactive rank per entered slot: predict_next_stateless scored against
prior entered context, entered song located in top-10.

Relates to #6

🤖 assist"
```

---

### Task 3: Frontend — add `hit_rank` to `PreviewSlot`

**Files:**
- Modify: `web/src/lib/preview.ts:18-28`

**Step 1: Edit the interface**

Change `PreviewSlot` to:

```ts
export interface PreviewSlot {
  slot_idx: number;
  set_number: string;
  position: number;
  state: "entered" | "predicted";
  entered_song?: EnteredSong;
  top_k?: PreviewCandidate[];
  // 1..10 when the entered song was in the retroactive top-10 prediction;
  // null when it was outside that list. Absent on predicted slots.
  hit_rank?: number | null;
  pending?: "adding" | "removing";
}
```

**Step 2: Typecheck**

Run: `cd web && pnpm tsc --noEmit`

Expected: no errors.

**Step 3: Commit**

```bash
git add web/src/lib/preview.ts
git commit -m "feat(web): add hit_rank to PreviewSlot type

Relates to #6

🤖 assist"
```

---

### Task 4: Frontend — render the hit-rank indicator in `SlotRow`

**Files:**
- Modify: `web/src/components/FullPreview.tsx:52-106` (`SlotRow`, entered branch)
- Test: `web/src/components/FullPreview.test.tsx` (append four tests)

Rendering rules (from the design doc):

| `hit_rank` | `pending` | Indicator |
|---|---|---|
| 1 | none / "removing" | Bullseye SVG, `text-emerald-400` |
| 2..10 | none / "removing" | `#N`, `text-xs text-neutral-500 tabular-nums` |
| `null` | none / "removing" | `—`, `text-xs text-neutral-700` |
| any | `"adding"` | Suppress (spinner already present) |

**Step 1: Write the failing tests**

Append to `web/src/components/FullPreview.test.tsx`:

```tsx
function enteredSlot(
  opts: { hit_rank?: number | null; pending?: "adding" | "removing" } = {},
): PreviewSlot {
  return {
    slot_idx: 1,
    set_number: "1",
    position: 1,
    state: "entered",
    entered_song: { song_id: 7, name: "Buried Alive" },
    ...opts,
  };
}

test("entered slot with hit_rank=1 renders the bullseye icon", () => {
  render(<FullPreview slots={[enteredSlot({ hit_rank: 1 })]} onSlotClick={() => {}} />);
  expect(screen.getByTestId("hit-rank-bullseye")).toBeInTheDocument();
});

test("entered slot with hit_rank=3 renders the #N chip", () => {
  render(<FullPreview slots={[enteredSlot({ hit_rank: 3 })]} onSlotClick={() => {}} />);
  expect(screen.getByText("#3")).toBeInTheDocument();
  expect(screen.queryByTestId("hit-rank-bullseye")).not.toBeInTheDocument();
});

test("entered slot with hit_rank=null renders an em-dash", () => {
  render(<FullPreview slots={[enteredSlot({ hit_rank: null })]} onSlotClick={() => {}} />);
  expect(screen.getByTestId("hit-rank-miss")).toHaveTextContent("—");
});

test("entered slot in 'adding' pending state suppresses the hit-rank indicator", () => {
  render(
    <FullPreview
      slots={[enteredSlot({ hit_rank: 1, pending: "adding" })]}
      onSlotClick={() => {}}
    />,
  );
  expect(screen.queryByTestId("hit-rank-bullseye")).not.toBeInTheDocument();
  expect(screen.queryByTestId("hit-rank-miss")).not.toBeInTheDocument();
});
```

**Step 2: Verify the tests fail**

Run: `cd web && pnpm vitest run src/components/FullPreview.test.tsx`

Expected: the four new tests FAIL (element not found); existing tests still PASS.

**Step 3: Implement `HitRankIndicator` and wire it into `SlotRow`**

In `web/src/components/FullPreview.tsx`, add above `SlotRow`:

```tsx
function HitRankIndicator({ hitRank }: { hitRank: number | null | undefined }) {
  if (hitRank === undefined) return null;
  if (hitRank === 1) {
    return (
      <svg
        data-testid="hit-rank-bullseye"
        aria-label="Top prediction"
        viewBox="0 0 16 16"
        className="w-3.5 h-3.5 text-emerald-400 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <circle cx="8" cy="8" r="6.25" />
        <circle cx="8" cy="8" r="3.5" />
        <circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (hitRank === null) {
    return (
      <span
        data-testid="hit-rank-miss"
        className="text-xs text-neutral-700 tabular-nums shrink-0"
      >
        —
      </span>
    );
  }
  return (
    <span className="text-xs text-neutral-500 tabular-nums shrink-0">
      #{hitRank}
    </span>
  );
}
```

Then, inside the `state === "entered"` branch of `SlotRow`, after the spinner block (lines 77-82), add:

```tsx
{slot.pending !== "adding" && <HitRankIndicator hitRank={slot.hit_rank} />}
```

**Step 4: Verify tests pass**

Run: `cd web && pnpm vitest run src/components/FullPreview.test.tsx`

Expected: all tests PASS (existing + four new).

**Step 5: Run the full web test suite and typecheck**

Run in parallel:

- `cd web && pnpm vitest run`
- `cd web && pnpm tsc --noEmit`
- `cd web && pnpm lint`

Expected: all green, no regressions.

**Step 6: Commit**

```bash
git add web/src/components/FullPreview.tsx web/src/components/FullPreview.test.tsx
git commit -m "feat(web): render hit-rank indicator on entered slots

Rank 1 = bullseye icon, 2-10 = #N chip, null = em-dash, adding = hidden.
Reads PreviewSlot.hit_rank from the /preview response.

Fixes #6

🤖 assist"
```

---

### Task 5: Manual verification

After Task 4 commits, start the dev stack and eyeball the feature in a real show before pushing.

**Step 1: Start the backend and frontend**

Run in two shells:

- `cd api && uv run uvicorn phishpicker.api.app:app --reload --port 8000`
- `cd web && pnpm dev`

**Step 2: Open a browser to the live picker**

Navigate to `http://localhost:3000`. If there's an active live show, you should see entered slots with `#N` / bullseye / em-dash indicators right-aligned. If there's no active show, either (a) create one via the admin endpoints, or (b) add songs to an existing show through the UI.

**Step 3: Check cases**

- Add a song that is the top prediction → bullseye should appear once the slot settles (briefly shows no indicator during `pending="adding"`).
- Add a song that's NOT the top prediction → `#N` (or `—` if obscure).
- Confirm via phish.net sync that reconciliation doesn't change the indicator shape (rank depends on slot + context, not source).

**Step 4: Announce completion via ha-announce**

```bash
~/bin/ha-announce.sh "Phishpicker: hit-rank indicator is shipped locally, ready for your review" &
```

Run in background. If quiet mode is enabled (`~/.claude_ha_config.json`), skip this.

---

### Task 6: Wrap up

**Step 1: Push**

```bash
git push origin main
```

**Step 2: Close issue #6**

```bash
gh issue close 6 --comment "Shipped in $(git log -1 --pretty=%h) — retroactive hit-rank indicator on entered slots. Rank 1 = bullseye, 2-10 = #N chip, miss = em-dash."
```

---

## Notes for the implementer

- **Preserve the existing predicted-slot behavior.** Task 2 rebuilds `virtual_played` from scratch inside the loop, which is identical to the old one-shot initialization only when entered songs come in slot-iteration order. That matches the current UI invariant, but if you touch this later, keep the new structure — it's clearer.
- **No changes to the alternatives modal.** `SlotAltsModal` reads from `/alternatives`, which is unaffected. The hit-rank indicator is purely a `/preview` augmentation.
- **Do not cache `predict_next_stateless` output.** The retroactive rank for slot N depends on the *exact* prior entered context. The existing per-show caches (`stats_cache`, `ext_cache`, `bigram_cache`) still apply — just hand them through.
- **Out-of-top-10 is common and expected.** Phish's song catalog is huge; most slots won't be top-10 hits. The em-dash is the default outcome and isn't a bug.
