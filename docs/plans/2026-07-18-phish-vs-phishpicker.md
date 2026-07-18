# Phish vs. PhishPicker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a second, additive live scoring view that inverts the frozen foresight bracket — the band scores for songs the model didn't foresee, the model for songs it placed — switchable via a toggle beside the add-song control.

**Architecture:** A new pure scoring function `score_versus` reuses the existing `score_foresight` claims to decide, per played song, band-vs-picker; `score_live_show` attaches the result as a `versus` block on the existing score payload (no new endpoint, no extra round-trip). The frontend adds a `VersusBoard` and a persistent two-segment toggle that swaps only the main display region; the existing Picks view and scoring engine are untouched.

**Tech Stack:** Python (pure functions, sqlite3), FastAPI; Next.js/React, TypeScript, Vitest + Testing Library. Backend tests run with `uv run pytest` from `api/`; frontend with `npm test` from `web/`.

**Design doc:** `docs/plans/2026-07-18-phish-vs-phishpicker-design.md` — read it first for the why, the tour data, and the fairness model.

**Branch:** `feat/phish-vs-phishpicker` (already created; the design doc is committed there).

---

## Task 1: `score_versus` pure engine + constants

The heart of the feature. A pure function in the scoring engine that turns the
frozen bracket + actual setlist + per-song surprise weights into a band-vs-picker
tally. Reuses `score_foresight`'s consume-once claims: a played song is a PICKER
point if the bracket claimed it, a PHISH point otherwise.

**Files:**
- Modify: `api/src/phishpicker/scoring.py` (add constants near the other point
  ladders around line 20; add `score_versus` after `score_foresight`)
- Test: `api/tests/test_versus.py` (create)

**Step 1: Write the failing tests**

Create `api/tests/test_versus.py`:

```python
from phishpicker.scoring import (
    VS_BAND_BASE,
    VS_PICKER,
    score_versus,
)


def _actual(*specs):
    """specs are (song_id, set, position) triples in setlist order."""
    return [{"song_id": s, "set_number": st, "position": p} for s, st, p in specs]


def _bracket(*specs):
    return [{"song_id": s, "set_number": st, "position": p} for s, st, p in specs]


def test_exact_bracket_hit_scores_for_the_picker():
    # Song 100 predicted at (1,1) and played at (1,1) -> exact -> picker.
    br = _bracket((100, "1", 1))
    act = _actual((100, "1", 1))
    out = score_versus(br, act, surprise_by_song={})
    assert out["per_song"][0]["side"] == "picker"
    assert out["per_song"][0]["points"] == VS_PICKER["exact"]
    assert out["picker_total"] == VS_PICKER["exact"]
    assert out["phish_total"] == 0
    assert out["leader"] == "picker"


def test_song_absent_from_bracket_scores_for_phish():
    br = _bracket((100, "1", 1))
    act = _actual((999, "1", 1))  # not in the bracket at all
    out = score_versus(br, act, surprise_by_song={})
    ps = out["per_song"][0]
    assert ps["side"] == "phish"
    assert ps["points"] == VS_BAND_BASE  # no surprise bonus supplied
    assert out["leader"] == "phish"


def test_surprise_bonus_is_added_for_band_songs():
    br = _bracket((100, "1", 1))
    act = _actual((999, "1", 1))
    out = score_versus(br, act, surprise_by_song={999: (8, "absent-bustout")})
    ps = out["per_song"][0]
    assert ps["points"] == VS_BAND_BASE + 8
    assert ps["reason"] == "absent-bustout"


def test_right_set_scores_less_than_exact_but_still_picker():
    # Predicted (2,1), played (2,3): right set, wrong slot.
    br = _bracket((100, "2", 1))
    act = _actual((100, "2", 3))
    out = score_versus(br, act, surprise_by_song={})
    assert out["per_song"][0]["side"] == "picker"
    assert out["per_song"][0]["points"] == VS_PICKER["right_set"]
    assert VS_PICKER["right_set"] < VS_PICKER["exact"]


def test_tie_reports_tie():
    br = _bracket((100, "1", 1))
    # one exact picker hit + one absent band song weighted to match exactly
    act = _actual((100, "1", 1), (999, "2", 1))
    out = score_versus(
        br, act, surprise_by_song={999: (VS_PICKER["exact"] - VS_BAND_BASE, "absent")}
    )
    assert out["picker_total"] == out["phish_total"]
    assert out["leader"] == "tie"


def test_direction_matches_the_tour_magic_night():
    """Jul-12 shape: mostly right-set hits -> picker should win."""
    br = _bracket(*[(i, "1", i) for i in range(1, 9)],
                  *[(i, "2", i - 8) for i in range(9, 16)])
    # 8 of the played songs land in the right set (picker), 7 are absent (band).
    act = _actual(*[(i, "1", i) for i in range(1, 9)],
                  *[(900 + i, "2", i) for i in range(1, 8)])
    out = score_versus(br, act, surprise_by_song={})
    assert out["leader"] == "picker"


def test_direction_matches_the_tour_weird_night():
    """Jul-14 shape: bracket places almost nothing -> band should win."""
    br = _bracket(*[(i, "1", i) for i in range(1, 16)])
    act = _actual(*[(500 + i, "1", i) for i in range(1, 16)])  # all absent
    out = score_versus(br, act, surprise_by_song={})
    assert out["leader"] == "phish"
```

**Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_versus.py -q`
Expected: FAIL — `ImportError: cannot import name 'VS_PICKER'`.

**Step 3: Write minimal implementation**

In `api/src/phishpicker/scoring.py`, add the constants near the existing ladder
(just after the `OPENER_SLOTS` block around line 24):

```python
# Phish vs PhishPicker — a second, additive lens (see
# docs/plans/2026-07-18-phish-vs-phishpicker-design.md). Its own compressed
# ladder, independent of the foresight point values above. STARTING VALUES —
# calibrated to a fair coin after a few live shows; tune freely.
VS_PICKER = {"opener": 12, "exact": 10, "right_set": 6, "somewhere": 3}
VS_BAND_BASE = 5
VS_BAND_BUSTOUT_BONUS = 8
VS_BAND_RARE_BONUS = 3
```

Add `score_versus` right after `score_foresight` (after line ~92):

```python
def score_versus(
    bracket: list[dict],
    actual: list[dict],
    surprise_by_song: dict[int, tuple[int, str]],
) -> dict:
    """Phish vs PhishPicker: invert the frozen bracket. Each played song scores
    for exactly one side — PICKER if the bracket claimed it (reusing
    score_foresight's consume-once placement), PHISH otherwise.

    surprise_by_song maps song_id -> (bonus_points, reason_tag) for absent
    (band) songs; the caller computes it from rarity/bustout stats. Pure — no DB.
    """
    claims, _ = score_foresight(bracket, actual)
    per_song: list[dict] = []
    picker_total = phish_total = 0
    for i, row in enumerate(actual):
        claim = claims.get(i)
        if claim is not None:
            pts = VS_PICKER.get(claim["reason"], VS_PICKER["somewhere"])
            picker_total += pts
            per_song.append({"index": i, "song_id": row["song_id"],
                             "side": "picker", "points": pts,
                             "reason": claim["reason"]})
        else:
            bonus, tag = surprise_by_song.get(row["song_id"], (0, "absent"))
            pts = VS_BAND_BASE + bonus
            phish_total += pts
            per_song.append({"index": i, "song_id": row["song_id"],
                             "side": "phish", "points": pts, "reason": tag})
    leader = ("picker" if picker_total > phish_total
              else "phish" if phish_total > picker_total else "tie")
    return {"picker_total": picker_total, "phish_total": phish_total,
            "leader": leader, "per_song": per_song}
```

**Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_versus.py -q`
Expected: PASS (7 passed).

**Step 5: Commit**

```bash
git add api/src/phishpicker/scoring.py api/tests/test_versus.py
git commit -m "feat(scoring): score_versus — invert the frozen bracket for the vs-game"
```

---

## Task 2: Compute surprise weights + attach `versus` to the score payload

Wire the pure engine into the live score so the frontend gets a `versus` block
on the existing `GET /api/live/show/{id}/score` response — no new endpoint.

**Files:**
- Modify: `api/src/phishpicker/scoring_service.py` (import `score_versus` +
  constants; add `_surprise_weights`; attach `result["versus"]` in
  `score_live_show` after the `result = score_show(...)` assembly, ~line 94)
- Test: `api/tests/test_scoring_service_versus.py` (create)

**Step 1: Write the failing test**

Create `api/tests/test_scoring_service_versus.py`. Reuse the existing live-DB
fixtures — check `api/tests/conftest.py` for `seeded_read_db` / a live-show
fixture and mirror the pattern used in `api/tests/test_live.py` for freezing a
bracket and entering songs. The test must:

```python
# Pattern (adapt fixture names to conftest.py):
# 1. seed read DB + live show, freeze a bracket, enter a multi-set setlist where
#    at least one entered song IS a bracket pick and at least one is NOT.
# 2. result = score_live_show(read_conn, live_conn, show_id)
# 3. assert "versus" in result
#    v = result["versus"]
#    assert set(v) == {"picker_total", "phish_total", "leader", "per_song"}
#    assert len(v["per_song"]) == <number of entered songs>
#    assert all("name" in ps for ps in v["per_song"])   # names resolved
#    assert {ps["side"] for ps in v["per_song"]} <= {"picker", "phish"}
#    # the bracket-matching song is picker; the off-bracket song is phish
```

Keep it a real integration test through `score_live_show`, not a re-test of the
pure function (Task 1 covers that).

**Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_scoring_service_versus.py -q`
Expected: FAIL — `KeyError: 'versus'` (block not attached yet).

**Step 3: Write minimal implementation**

In `api/src/phishpicker/scoring_service.py`:

Add to the imports from `phishpicker.scoring`:
```python
from phishpicker.scoring import (
    VS_BAND_BUSTOUT_BONUS,
    VS_BAND_RARE_BONUS,
    score_show,
    score_versus,
)
```
(Merge with the existing `from phishpicker.scoring import ...` line.)

Add a module-level helper:
```python
# Below this many all-time plays a song counts as a "deep cut" — a bigger flex
# for the band when the model didn't see it coming. Tunable.
VS_RARE_PLAYS_MAX = 50


def _surprise_weights(
    read_conn: sqlite3.Connection,
    actual: list[dict],
    bustout_song_ids: set[int],
) -> dict[int, tuple[int, str]]:
    """Per absent-song band bonus: bustout > deep cut > common. One cheap query."""
    ids = [r["song_id"] for r in actual]
    plays: dict[int, int] = {sid: 0 for sid in ids}
    if ids:
        ph = ",".join("?" * len(ids))
        for sid, c in read_conn.execute(
            f"SELECT song_id, COUNT(*) FROM setlist_songs "
            f"WHERE song_id IN ({ph}) GROUP BY song_id", ids
        ).fetchall():
            plays[sid] = c
    out: dict[int, tuple[int, str]] = {}
    for sid in ids:
        if sid in bustout_song_ids:
            out[sid] = (VS_BAND_BUSTOUT_BONUS, "absent-bustout")
        elif plays.get(sid, 0) < VS_RARE_PLAYS_MAX:
            out[sid] = (VS_BAND_RARE_BONUS, "absent-rare")
        else:
            out[sid] = (0, "absent")
    return out
```

In `score_live_show`, right after `result = score_show(...)` finishes and the
`_name` helper is defined (~line 94), add:
```python
    versus = score_versus(bracket, actual, _surprise_weights(
        read_conn, actual, bustout_song_ids))
    for ps in versus["per_song"]:
        ps["name"] = _name(ps["song_id"])
    result["versus"] = versus
```

**Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_scoring_service_versus.py -q`
Then the full backend suite to confirm nothing regressed:
Run: `cd api && uv run ruff check . && uv run pytest -q`
Expected: PASS (all green).

**Step 5: Commit**

```bash
git add api/src/phishpicker/scoring_service.py api/tests/test_scoring_service_versus.py
git commit -m "feat(scoring): attach versus block (rarity-graded band points) to the live score"
```

---

## Task 3: Frontend types + `VersusBoard` component

**Files:**
- Modify: `web/src/lib/score.ts` (add `VersusSong` / `Versus` interfaces; add
  `versus?: Versus` to `ScoreResponse` at ~line 63)
- Create: `web/src/components/VersusBoard.tsx`
- Test: `web/src/components/VersusBoard.test.tsx` (create)

**Step 1: Write the failing test**

Create `web/src/components/VersusBoard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { VersusBoard } from "./VersusBoard";

const versus = {
  picker_total: 22,
  phish_total: 40,
  leader: "phish" as const,
  per_song: [
    { index: 0, song_id: 1, name: "Tweezer", side: "picker" as const, points: 10, reason: "exact" },
    { index: 1, song_id: 2, name: "Icculus", side: "phish" as const, points: 13, reason: "absent-bustout" },
  ],
};

test("shows both totals and who's leading", () => {
  render(<VersusBoard versus={versus} />);
  expect(screen.getByTestId("vs-picker-total")).toHaveTextContent("22");
  expect(screen.getByTestId("vs-phish-total")).toHaveTextContent("40");
  expect(screen.getByTestId("vs-leader")).toHaveTextContent(/phish/i);
});

test("lists each played song on its scoring side", () => {
  render(<VersusBoard versus={versus} />);
  const tweezer = screen.getByText("Tweezer").closest("[data-side]");
  expect(tweezer).toHaveAttribute("data-side", "picker");
  const icculus = screen.getByText("Icculus").closest("[data-side]");
  expect(icculus).toHaveAttribute("data-side", "phish");
});
```

**Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/VersusBoard.test.tsx`
Expected: FAIL — cannot resolve `./VersusBoard`.

**Step 3: Write minimal implementation**

In `web/src/lib/score.ts`, add near the other interfaces:
```ts
export interface VersusSong {
  index: number;
  song_id: number;
  name: string;
  side: "picker" | "phish";
  points: number;
  reason: string;
}

export interface Versus {
  picker_total: number;
  phish_total: number;
  leader: "picker" | "phish" | "tie";
  per_song: VersusSong[];
}
```
And add to `ScoreResponse`:
```ts
  versus?: Versus;
```

Create `web/src/components/VersusBoard.tsx`. Match the visual language of the
existing dark-theme components (see `ScoreHero.tsx` / `ScoreFeed.tsx` for the
Tailwind palette — `bg-neutral-950`, indigo accents). A tug-of-war bar (two
proportional widths) over a per-song list:

```tsx
import type { Versus } from "@/lib/score";

export function VersusBoard({ versus }: { versus: Versus }) {
  const { picker_total, phish_total, leader, per_song } = versus;
  const total = picker_total + phish_total || 1;
  const phishPct = Math.round((phish_total / total) * 100);
  const leaderLabel =
    leader === "tie" ? "Dead even" : leader === "phish" ? "Phish leads" : "PhishPicker leads";

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold text-emerald-400">Phish</span>
        <span data-testid="vs-leader" className="text-xs text-neutral-400">
          {leaderLabel}
        </span>
        <span className="font-semibold text-indigo-400">PhishPicker</span>
      </div>

      <div className="flex items-center gap-2">
        <span data-testid="vs-phish-total" className="w-8 text-right text-emerald-400 font-bold">
          {phish_total}
        </span>
        <div className="flex-1 h-3 rounded-full overflow-hidden bg-indigo-500">
          <div className="h-full bg-emerald-500" style={{ width: `${phishPct}%` }} />
        </div>
        <span data-testid="vs-picker-total" className="w-8 text-indigo-400 font-bold">
          {picker_total}
        </span>
      </div>

      <ul className="flex flex-col gap-1">
        {per_song.map((s) => (
          <li
            key={s.index}
            data-side={s.side}
            className={`flex items-center justify-between rounded px-3 py-2 text-sm ${
              s.side === "phish"
                ? "bg-emerald-950/40 border-l-2 border-emerald-500"
                : "bg-indigo-950/40 border-l-2 border-indigo-500"
            }`}
          >
            <span className="truncate">{s.name}</span>
            <span className="flex items-center gap-2 text-xs text-neutral-400">
              <span>{s.reason}</span>
              <span className={s.side === "phish" ? "text-emerald-400" : "text-indigo-400"}>
                +{s.points}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

**Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/VersusBoard.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/src/lib/score.ts web/src/components/VersusBoard.tsx web/src/components/VersusBoard.test.tsx
git commit -m "feat(web): VersusBoard — Phish vs PhishPicker tug-of-war scoreboard"
```

---

## Task 4: `useLiveView` hook (persisted toggle state) + `LiveViewToggle`

**Files:**
- Create: `web/src/lib/liveView.ts`
- Create: `web/src/components/LiveViewToggle.tsx`
- Test: `web/src/lib/liveView.test.ts` (create)
- Test: `web/src/components/LiveViewToggle.test.tsx` (create)

**Step 1: Write the failing tests**

Create `web/src/lib/liveView.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { useLiveView } from "./liveView";

beforeEach(() => localStorage.clear());

test("defaults to the picks view", () => {
  const { result } = renderHook(() => useLiveView());
  expect(result.current[0]).toBe("picks");
});

test("persists the chosen view across remounts", () => {
  const first = renderHook(() => useLiveView());
  act(() => first.result.current[1]("vs"));
  expect(localStorage.getItem("phishpicker:liveView")).toBe("vs");
  const second = renderHook(() => useLiveView());
  expect(second.result.current[0]).toBe("vs");
});
```

Create `web/src/components/LiveViewToggle.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { LiveViewToggle } from "./LiveViewToggle";

test("marks the active segment and fires onChange", () => {
  const onChange = vi.fn();
  render(<LiveViewToggle value="picks" onChange={onChange} />);
  expect(screen.getByRole("button", { name: /picks/i })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: /vs/i }));
  expect(onChange).toHaveBeenCalledWith("vs");
});
```

**Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/liveView.test.ts src/components/LiveViewToggle.test.tsx`
Expected: FAIL — modules not found.

**Step 3: Write minimal implementations**

Create `web/src/lib/liveView.ts`:

```ts
import { useEffect, useState } from "react";

export type LiveView = "picks" | "vs";
const KEY = "phishpicker:liveView";

export function useLiveView(): [LiveView, (v: LiveView) => void] {
  const [view, setView] = useState<LiveView>("picks");

  // Read persisted choice after mount (SSR-safe — no localStorage on server).
  useEffect(() => {
    const saved = localStorage.getItem(KEY);
    if (saved === "vs" || saved === "picks") setView(saved);
  }, []);

  const set = (v: LiveView) => {
    setView(v);
    localStorage.setItem(KEY, v);
  };
  return [view, set];
}
```

Create `web/src/components/LiveViewToggle.tsx`:

```tsx
import type { LiveView } from "@/lib/liveView";

export function LiveViewToggle({
  value,
  onChange,
}: {
  value: LiveView;
  onChange: (v: LiveView) => void;
}) {
  const seg = (v: LiveView, label: string) => (
    <button
      type="button"
      aria-pressed={value === v}
      onClick={() => onChange(v)}
      className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors ${
        value === v ? "bg-neutral-700 text-white" : "text-neutral-400"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="flex gap-1 rounded-lg bg-neutral-900 p-1">
      {seg("picks", "Picks")}
      {seg("vs", "VS")}
    </div>
  );
}
```

**Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/lib/liveView.test.ts src/components/LiveViewToggle.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/src/lib/liveView.ts web/src/lib/liveView.test.ts web/src/components/LiveViewToggle.tsx web/src/components/LiveViewToggle.test.tsx
git commit -m "feat(web): persisted live-view toggle (Picks | VS)"
```

---

## Task 5: Wire the toggle + board into the live page

Swap only the main display region on toggle; keep `PlayedStrip` and
`AddSongSheet` shared. Toggle sits just above `AddSongSheet` (thumb zone).

**Files:**
- Modify: `web/src/app/page.tsx` (imports; add `useLiveView`; conditionally
  render `VersusBoard` vs the existing Picks block inside `<main>` ~lines
  318–332; render `<LiveViewToggle>` immediately before `<AddSongSheet>` ~line
  344)

**Step 1: Write the change**

Add imports at the top of `web/src/app/page.tsx`:
```tsx
import { VersusBoard } from "@/components/VersusBoard";
import { LiveViewToggle } from "@/components/LiveViewToggle";
import { useLiveView } from "@/lib/liveView";
```

Inside the component, add near the other hooks:
```tsx
  const [liveView, setLiveView] = useLiveView();
```

In the `<main>` render, replace the current Picks block (the `<>` containing
`ScoreTeaser`, `PlayedStrip`, `FullPreview`, and the recap link) so that
`PlayedStrip` and the recap link stay shared but the scoreboard region switches:

```tsx
        ) : (
          <>
            {liveView === "vs" && score?.versus ? (
              <VersusBoard versus={score.versus} />
            ) : (
              <>
                {score && score.attributions.length > 0 && (
                  <ScoreTeaser totals={score.totals} />
                )}
                <FullPreview
                  slots={slots}
                  currentSet={currentSet}
                  loading={!preview}
                  onSlotClick={setActiveSlot}
                  onSetChange={handleSetChange}
                />
              </>
            )}

            <PlayedStrip songs={playedSongs} onUndo={handleUndo} />

            <a
              href={`/recap?show=${showId}`}
              className="text-xs text-neutral-600 hover:text-indigo-400 self-start mt-2"
            >
              End show → recap
            </a>
          </>
        )}
```
(`PlayedStrip` is shared across both views; only the scoreboard region swaps.)

Render the toggle just before the add-song sheet:
```tsx
      {showId && (
        <div className="px-4 pb-2">
          <LiveViewToggle value={liveView} onChange={setLiveView} />
        </div>
      )}
      {showId && <AddSongSheet songs={songs} onAdd={handleAdd} />}
```

**Step 2: Typecheck + build**

Run: `cd web && npm run lint && npm run build`
Expected: passes (no type errors).

**Step 3: Manual verification with the run skill**

`page.tsx` is integration-heavy; verify by driving the real app rather than a
unit test. Use the `verify` / `run` skill (or `npm run dev`), then:
1. Start/attach a live show, enter a few songs (mix of bracket hits and misses).
2. Confirm the toggle appears above the add-song control.
3. Tap **VS** → the tug-of-war board replaces the Picks/preview area; totals and
   per-song sides render; `PlayedStrip` and the add-song control stay put.
4. Add another song in VS view → the board updates without switching back.
5. Reload mid-show → it reopens on **VS** (localStorage persistence).
6. Tap **Picks** → the original view returns unchanged.

**Step 4: Commit**

```bash
git add web/src/app/page.tsx
git commit -m "feat(web): switch the live view between Picks and VS via the bottom toggle"
```

---

## Task 6: Full verification pass

**Step 1: Backend**

Run: `cd api && uv run ruff check . && uv run pytest -q`
Expected: all green.

**Step 2: Frontend**

Run: `cd web && npm run lint && npm test && npm run build`
Expected: all green.

**Step 3: End-to-end sanity (optional but recommended)**

Reproduce the design's golden claim against real data: with the tour setlists
available, confirm a Jul-12-shaped show comes out PhishPicker-leaning and a
Jul-14-shaped show comes out Phish-leaning in the actual `versus` payload
(Task 1's direction tests already assert this at the unit level).

**Step 4: Finish the branch**

Do NOT merge to `main` unprompted — merging auto-deploys to prod. Use the
`superpowers:finishing-a-development-branch` skill to present options, and let
David choose whether/when to deploy. Fold the parked
`fix/close-out-set-advance` branch into the same deploy if he ships this
(see memory: it's been waiting for the next deploy).

---

## Notes for the implementer

- **Calibration is intentionally rough for v1.** The point constants in Task 1
  are starting guesses; the direction tests (Jul-12 picker, Jul-14 band) are the
  real contract. David will tune magnitudes after watching a few live shows.
- **Do not touch the existing scoring engine or Picks view.** `score_show`,
  foresight/live ledgers, `FullPreview`, `ScoreTeaser` all stay as-is. This is
  purely additive.
- **No new endpoint.** The `versus` block rides the existing
  `GET /api/live/show/{id}/score` payload, so it updates live with every song
  entry at no extra network cost.
- **Out of scope (YAGNI):** VS history, VS leaderboard, VS push notifications,
  live-updating variant. Not in this plan.
