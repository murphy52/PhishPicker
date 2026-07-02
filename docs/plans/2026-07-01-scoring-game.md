# Scoring Game Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn phishpicker into a self-scored prediction game — score how well the app's own predictions land, both pre-show (frozen bracket) and live (next-song calls), with a live scoreboard and a post-show scorecard.

**Architecture:** A **pure scoring engine** (`scoring.py`) is a function of `(frozen bracket JSON, actual setlist, captured live-prediction JSON)` → ledger totals + per-song attributions. The model is run **once per slot, live**, its output captured as JSON in `live.db`; scoring **never re-runs the model** (capture-don't-recompute). Best-claim-wins: each actual song banks the higher of its Foresight/Live *base* claims, once. A live combo (cap ×2) multiplies only Live-banked points.

**Tech Stack:** Python 3.12 / FastAPI / SQLite (`api/`), LightGBM ranker, Next.js PWA (`web/`). Tests: `pytest` via `uv run pytest` (run from `api/`). Design doc: `docs/plans/2026-07-01-scoring-game-design.md`.

**Conventions:** TDD (red→green→commit). Run all commands from `api/`. Commit after each green step. Match commit style `type: subject` + `🤖 assist` footer.

---

## Phase 0 — Prerequisites (independent bugs/helpers)

### Task 0.1: Allow `E2`/`E3` in the live schema (fixes a real crash)

phish.net sync produces `set_number='E2'` but `live_songs`/`live_show` CHECK constraints reject it → `append_song` crashes on any double encore. Fix before anything else.

**Files:**
- Modify: `api/src/phishpicker/db/live_schema.sql` (the `live_songs.set_number` CHECK and `live_show.current_set` CHECK)
- Test: `api/tests/test_live.py` (or a new `api/tests/test_e2_encore.py`)

**Step 1 — Write the failing test.** In `api/tests/test_e2_encore.py`:
```python
from phishpicker.db.connection import open_db, apply_live_schema
from phishpicker.live import create_live_show, append_song

def test_append_e2_encore_song(tmp_path):
    c = open_db(tmp_path / "live.db"); apply_live_schema(c)
    show_id = create_live_show(c, show_date="2026-07-07", venue_id=1)  # returns str
    append_song(c, show_id, song_id=1, set_number="E")
    append_song(c, show_id, song_id=2, set_number="E2")  # must not raise
    rows = c.execute("SELECT set_number FROM live_songs ORDER BY entered_order").fetchall()
    assert [r["set_number"] for r in rows] == ["E", "E2"]
```

**Step 2 — Run, expect fail:** `uv run pytest tests/test_e2_encore.py -v` → FAIL (CHECK constraint / IntegrityError).

**Step 3 — Implement:** in `live_schema.sql` change both CHECKs to include `E2`,`E3`:
```sql
-- live_show
current_set TEXT NOT NULL DEFAULT '1' CHECK (current_set IN ('1','2','3','4','E','E2','E3')),
-- live_songs
set_number TEXT NOT NULL CHECK (set_number IN ('1','2','3','4','E','E2','E3')),
```
Because `apply_live_schema` uses `CREATE TABLE IF NOT EXISTS`, add a note/migration for existing `live.db` files (dev can delete the local `live.db`; prod live.db is ephemeral per-show). Confirm how `apply_live_schema` runs and whether a migration helper exists.

**Step 4 — Run, expect pass.** `uv run pytest tests/test_e2_encore.py -v` → PASS.

**Step 5 — Commit:** `git commit -am "fix(live): allow E2/E3 encores in live schema"`

---

### Task 0.2: Deterministic prediction tiebreak

`predict_next_stateless` (and the preview) sort by score with no stable secondary key, so rank-1 ties resolve to SQLite row order → the live next-song call can flip nondeterministically. Make it deterministic.

**Files:**
- Modify: `api/src/phishpicker/predict.py` (the final `scored.sort(...)`, ~line 61) and the candidate query if it lacks `ORDER BY`.
- Test: `api/tests/test_predict_determinism.py`

**Step 1 — Failing test:** score the same fixture twice, assert identical ordered `song_id`s including ties. (Construct a tiny DB where two songs tie; assert the lower `song_id` ranks first.)

**Step 2 — Run, expect fail** (or flaky). 

**Step 3 — Implement:** change the sort to a deterministic key: `scored.sort(key=lambda x: (-x[1], x[0]))` (score desc, song_id asc). Add `ORDER BY song_id` to the candidate `SELECT song_id FROM songs`.

**Step 4 — Run, expect pass.**

**Step 5 — Commit:** `git commit -am "fix(predict): deterministic tiebreak by song_id"`

---

### Task 0.3: Setlist normalizer (filter soundcheck, sort by set+position)

A shared helper the engine and callers use to turn raw rows into a clean scored setlist.

**Files:**
- Create: `api/src/phishpicker/scoring.py` (start the module)
- Test: `api/tests/test_scoring_setlist.py`

**Step 1 — Failing test:**
```python
from phishpicker.scoring import normalize_setlist

def test_normalize_filters_soundcheck_and_sorts():
    rows = [
        {"set_number":"S","position":1,"song_id":99},
        {"set_number":"E","position":1,"song_id":5},
        {"set_number":"1","position":2,"song_id":2},
        {"set_number":"1","position":1,"song_id":1},
    ]
    out = normalize_setlist(rows)
    assert [(r["set_number"], r["position"], r["song_id"]) for r in out] == [
        ("1",1,1), ("1",2,2), ("E",1,5)
    ]  # 'S' dropped; ordered by set then position
```

**Step 2 — Run, expect fail** (module/func missing).

**Step 3 — Implement** in `scoring.py`:
```python
_SET_ORDER = {"1":1,"2":2,"3":3,"4":4,"E":5,"E2":6,"E3":7}  # 'S' intentionally absent

def normalize_setlist(rows):
    kept = [r for r in rows if r["set_number"] in _SET_ORDER]
    return sorted(kept, key=lambda r: (_SET_ORDER[r["set_number"]], r["position"]))
```

**Step 4 — Run, expect pass.**

**Step 5 — Commit:** `git commit -am "feat(scoring): setlist normalizer (drop soundcheck, order by set+position)"`

---

### Task 0.4: `build_preview` handles `E2`/`E3` (mid-encore previews must not corrupt)

Task 0.1 makes `E2` rows reachable, but `build_preview` (`live_preview.py`) hardcodes `set_order = {"1":1,"2":2,"E":3}` and its structure loop only emits sets 1/2/E. During a double encore: entered `E2` songs are invisible to the slot loop (never join `virtual_played`), and with `current_set='E2'`, `_n_for` treats sets 1/2/E as *future* and re-opens them with default predicted slots — corrupting exactly the snapshots Task 2.3 captures. Fix before Phase 2.

**Files:** modify `api/src/phishpicker/live_preview.py`; test `api/tests/test_preview_e2.py`

**Step 1 — Failing test:** seed a live show with full sets 1/2, an `E` song, an `E2` song, `current_set='E2'`. Assert: (a) sets 1/2/E show *only* entered slots (no phantom predicted slots), (b) the entered `E2` song appears in the preview and in `virtual_played` (i.e., it is excluded from any predicted slot's candidates), (c) exactly one predicted slot exists for the next `E2` song.

**Step 3 — Implement:**
- Extend `set_order` to `{"1":1,"2":2,"E":3,"E2":4,"E3":5}` so past-set logic closes sets correctly when `current_set` is `E2`/`E3`.
- Make `structure` dynamic: the base `[("1",set1),("2",set2),("E",enc)]` plus, when `current_set` is `E2`/`E3`, append `(current_set, _n_for(current_set, 1))` so entered `E2`/`E3` songs render and one next-song slot exists.
- **Ruling (documented, accepted for v1):** the frozen bracket only ever predicts `("E", 1..encore_size)` — we never *predict into* `E2`/`E3` pre-show. A real second-encore song arriving as `("E2",1)` scores Foresight "somewhere" (5). The design's "`E2` exact = 40" tier is unreachable in v1.

**Step 5 — Commit:** `git commit -am "fix(preview): handle E2/E3 sets in build_preview"`

---

## Phase 1 — Pure scoring engine (`scoring.py`)

The engine takes plain dicts/lists (no DB) so it is trivially testable. Inputs:
- `bracket`: `list[{"set_number","position","song_id"}]` — frozen pre-show picks.
- `actual`: normalized setlist (from Task 0.3).
- `next_call_by_index`: `dict[int, int|None]` — the model's #1 next-song prediction that was live right *before* `actual[i]` was revealed, for `i>=1` (derived from captured snapshots by the caller). **Semantics: key absent or `None` = no call was captured (sync gap, sha-mismatch skip) → a no-event: the streak neither advances nor resets. A present-but-wrong `song_id` = a miss → streak resets.** Only genuine wrong calls punish the combo.
- `early_called_indices`: `set[int]` — actual indices the model had correctly placed 2+ slots ahead in an earlier snapshot (for the `🔭` badge only). Optional; empty set fine for v1.
- `bustout_song_ids`: `set[int]` — song_ids that are *genuine* bustouts/debuts, supplied by the caller (derived from `songs.is_bustout_placeholder`, which `live_sync._resolve_or_insert_song` already sets, plus any gap-threshold rule later). The engine must NOT infer bustouts from "no claim + no correct call" — that's just a miss. Misses stay in the PPS denominator and are listed as "songs that beat the app"; only `bustout_song_ids` members get the `🎸 BUSTOUT` flag and PPS exclusion.

Point constants (module-level, tunable):
```python
PTS_SOMEWHERE, PTS_RIGHT_SET, PTS_EXACT, PTS_OPENER = 5, 15, 40, 60
PTS_NEXT_SONG = 30
COMBO = {1:1.0, 2:1.5}  # 3rd+ -> 2.0 (cap)
OPENER_SLOTS = {("1",1), ("2",1), ("3",1), ("4",1), ("E",1)}  # E2/E3 openers NOT bonus-eligible
```

### Task 1.1: Foresight placement classification

**Files:** modify `scoring.py`; test `api/tests/test_scoring_foresight.py`

**Step 1 — Failing tests:** given a bracket pick song and the actual setlist, classify best occurrence. (Test sketches below use tuples for brevity — the real API takes the same dict shape as the engine inputs: `{"set_number","position","song_id"}`. Pick one shape and use it everywhere.)
```python
from phishpicker.scoring import classify_foresight
# actual: [("1",1,10),("1",2,20),("2",1,30)]
def test_exact(): assert classify_foresight(("1",1,10), ACTUAL) == ("exact", 40)
def test_opener_bonus(): assert classify_foresight(("1",1,10), ACTUAL) # opener slot -> 60 handled in 1.2
def test_right_set(): assert classify_foresight(("1",5,20), ACTUAL) == ("right_set", 15)
def test_somewhere(): assert classify_foresight(("2",1,20), ACTUAL) == ("somewhere", 5)  # 20 played in set 1
def test_absent(): assert classify_foresight(("1",1,999), ACTUAL) == ("absent", 0)
```

**Step 3 — Implement** `classify_foresight(pick, actual)`:
- find all actual rows with `song_id == pick.song_id` (its occurrences);
- if none → `("absent", 0)`;
- if any occurrence has same set+position as pick → `("exact", PTS_EXACT)`;
- elif any occurrence shares the pick's set → `("right_set", PTS_RIGHT_SET)`;
- else `("somewhere", PTS_SOMEWHERE)`.
Return the *best* (exact > right_set > somewhere). "Consumed once" bookkeeping handled in 1.2 across the whole bracket.

**Step 5 — Commit:** `feat(scoring): foresight placement classification`

### Task 1.2: Foresight ledger (opener bonus, consume-once)

**Step 1 — Failing tests:** whole-bracket Foresight pass returns per-song base + reason; exact hit on an opener slot yields 60; an E2 opener yields 40 (exact, no bonus); each actual occurrence is claimed by at most one bracket pick (consume-once for identical song_ids).

**Step 3 — Implement** `score_foresight(bracket, actual) -> dict[actual_index -> {base, reason}]`:
- For each bracket pick, classify; if `exact` and `(set,position) in OPENER_SLOTS` → base `PTS_OPENER`.
- Map the claim to the *actual index* it matched (best occurrence). If two bracket picks match the same actual occurrence (shouldn't happen — bracket is deduped), keep the higher base.
- For a repeated identical song_id: each actual occurrence can be matched by at most one pick; extra occurrences get no Foresight claim (eligible for Live).
- Also return **per-pick outcomes** (including `absent` picks that matched nothing) alongside the per-actual-index claims — the Phase-5 recap needs "which bracket picks whiffed" and shouldn't re-derive it. Suggested shape: `(claims_by_actual_index, pick_outcomes)`.

**Step 5 — Commit:** `feat(scoring): foresight ledger with opener bonus`

### Task 1.3: Live next-song scoring

**Step 1 — Failing tests:** given `next_call_by_index`, an actual index whose song matches its live call gets base `PTS_NEXT_SONG`; mismatch → 0/None; index 0 (opener) is never a live event.

**Step 3 — Implement** `score_live(actual, next_call_by_index) -> dict[actual_index -> {base}]`:
- for `i in range(1, len(actual))`: if `next_call_by_index.get(i) == actual[i].song_id` → live base `PTS_NEXT_SONG`.

**Step 5 — Commit:** `feat(scoring): live next-song base scoring`

### Task 1.4: Best-claim-wins resolution

**Step 1 — Failing tests:** foresight-exact(40) beats live(30) → banks Foresight; foresight-somewhere(5) vs live(30) → banks Live 30; only one ledger per song; reason strings include the beaten claim.

**Step 3 — Implement** `resolve_claims(foresight, live) -> list[attribution]` per actual index:
- compare **base** values; take max; attribution = `{index, ledger, base, reason, beaten_claim}`.
- ties → Foresight wins (premium tier).

**Step 5 — Commit:** `feat(scoring): best-claim-wins resolution`

### Task 1.5: Streak / combo (decoupled, ×2 cap, bustout breaks)

**Step 1 — Failing tests:**
- streak counts consecutive correct next-song calls regardless of ledger;
- a correct call that banks Foresight advances the streak but is NOT multiplied;
- a Live-banked call during a ×2 streak → 60;
- a miss (wrong call — including a bustout the model called something else for) resets streak to 0;
- **no captured call (`next_call_by_index.get(i)` is None/absent) is a no-event: streak neither advances nor resets** (sync gaps and sha-mismatch skips must not punish the combo);
- combo caps at ×2 (3rd, 4th… all ×2).

**Step 3 — Implement** `apply_combo(actual, attributions, next_call_by_index)`:
- iterate `i` in order; `call = next_call_by_index.get(i)`;
- if `call is None`: no-event — streak unchanged, `final = base`;
- elif `call == actual[i].song_id` (called right): `streak += 1`; if attribution[i].ledger == "live": `mult = COMBO.get(streak, 2.0)`; `final = base * mult`;
- else (wrong call): `streak = 0`; live/foresight `final = base`;
- Foresight-banked songs: `final = base` (never multiplied) even if `called_right`.
- record `streak` and `mult` per index for the UI timeline.

**Step 5 — Commit:** `feat(scoring): combo multiplier decoupled from ledger`

### Task 1.6: Look-ahead badge (0 points) + bustout/miss flags

**Step 1 — Failing tests:** an actual index in `early_called_indices` gets a `called_early=True` flag and 0 points; a song whose `song_id` is in `bustout_song_ids` is flagged `bustout=True`; a song with no bracket claim and no correct live call that is NOT in `bustout_song_ids` is flagged `missed=True` (plain miss — no celebration, stays in PPS denominator).

**Step 3 — Implement** flags in the attribution list. No points. Bustout status comes ONLY from the `bustout_song_ids` input — never inferred from misses (see Phase-1 inputs).

**Step 5 — Commit:** `feat(scoring): called-early badge + bustout/miss flags`

### Task 1.7: Totals + points-per-predictable-song

**Step 1 — Failing tests:** `foresight_total`, `live_total`, `combined`; PPS denominator excludes only `bustout=True` songs — a plain `missed=True` song stays in the denominator (the metric must not self-grade by dropping whiffs).

**Step 3 — Implement** `summarize(attributions) -> {foresight_total, live_total, combined, ppps, hit_counts}` where `ppps = combined / max(1, num_non_bustout_songs)` and `num_non_bustout_songs` counts all actual songs minus `bustout=True` ones.

**Step 5 — Commit:** `feat(scoring): score totals and points-per-predictable-song`

### Task 1.8: End-to-end engine over a full show fixture

**Step 1 — Failing test:** a hand-built imaginary show (the design doc's Chalk Dust / Reba / Ghost / Tweezer / Fluffhead / Loving Cup example) with a known bracket + `next_call_by_index` → assert exact per-song attributions, ledger totals, streak timeline. This is the regression anchor.

**Step 3 — Implement** the top-level `score_show(bracket, actual, next_call_by_index, early_called_indices, bustout_song_ids) -> ScoreResult` composing 1.1–1.7.

**Step 5 — Commit:** `feat(scoring): end-to-end score_show engine`

---

## Phase 2 — Storage & freeze

### Task 2.1: `live_score_state` table

**Files:** modify `api/src/phishpicker/db/live_schema.sql`; test `api/tests/test_score_state.py`
```sql
CREATE TABLE IF NOT EXISTS live_score_state (
    show_id       TEXT PRIMARY KEY REFERENCES live_show(show_id) ON DELETE CASCADE,
    model_sha     TEXT,
    frozen_bracket TEXT,   -- JSON: [{"set_number","position","song_id"}]
    snapshots      TEXT,   -- JSON: [{"after_count":N, "remaining":[{"set_number","position","song_id"}]}]
    updated_at     TEXT
);
```
TDD: helper `get_score_state`/`upsert_score_state` round-trips JSON. Commit.

### Task 2.2: Freeze the bracket at show start

**Files:** new `api/src/phishpicker/scoring_store.py` (freeze/capture helpers); modify BOTH live entry paths (manual `/live/song` in `app.py` AND `sync_show_with_phishnet` in `live_sync.py`); optionally also an explicit `/live/show/{id}/freeze` endpoint.
- `ensure_frozen(read_conn, live_conn, show_id)`: if `frozen_bracket` is null, call `build_preview(..., top_k=1)`; extract `[{set_number, position, song_id: top_k[0].song_id} for slot in slots if slot.state=="predicted"]`; store as `frozen_bracket`, stamp `model_sha`. Idempotent no-op otherwise.
- **CRITICAL ORDERING:** `build_preview` reads entered songs from the live DB and has no "pretend zero entered" parameter. If the freeze runs *after* the first insert, the opener slot comes back as `state="entered"` (no `top_k`) and the bracket silently loses the opener pick — the 60-pt slot. `ensure_frozen` MUST run **before** the first `live_songs` insert, in **both** write paths (the sync loop is the likely first-writer on sync-enabled nights).
TDD: freeze twice → bracket unchanged (idempotent); bracket is deduped one-per-slot; **freeze triggered via the append path includes the opener slot** (assert the bracket has a `("1",1)` entry). Commit.

### Task 2.3: Capture live-prediction snapshots

**Files:** modify `api/src/phishpicker/live_sync.py` (the append loop ~204-258 already computes a `predict_next_stateless` rank per append and discards the rest), the manual `append_song` path, AND the correction (`replace_song_at`) + `advance_set` paths.
- After each change, compute the remaining prediction (`build_preview(..., top_k=1)`), reduce to `[{set_number, position, song_id}]` for `state=="predicted"` slots, and append `{"after_count": len(entered), "remaining": [...]}` to `snapshots`.
- **Capture on ALL prediction-changing events:** song append, correction (`replace_song_at`), and `advance_set` (a set advance moves the next-song call from a speculative set-closer to the next set's opener). Corrections and set advances don't change the song count, so **multiple snapshots can share an `after_count` — that's expected; last-appended wins at read time** (Task 3.1).
- Refuse to append if `model_sha` differs from stored (log + skip, per design).
- **Concurrency:** manual entry and the sync poller write from different connections; appending to the `snapshots` JSON blob is an app-level read-modify-write. Wrap it in `BEGIN IMMEDIATE` (or route all captures through one helper that does) so simultaneous writers can't drop a snapshot.
- **Perf note (measure, don't guess):** this replaces one prediction call per append with a full `build_preview` (~18 slot predictions + one hit-rank prediction per already-entered song). Fine at a 60s poll cadence with the per-show caches, but log the capture duration; revisit if it grows past ~2s late in a show.
TDD: entering N songs yields N snapshots; each snapshot's first remaining entry = the live next-song call; a correction appends a snapshot with a duplicate `after_count`; `advance_set` appends a snapshot. Commit.

---

## Phase 3 — Score endpoint (recompute-on-read)

### Task 3.1: `GET /live/show/{id}/score`

**Files:** modify `api/src/phishpicker/app.py`; new `api/src/phishpicker/scoring_service.py` (glue: load state, derive engine inputs, call `score_show`); test `api/tests/test_score_endpoint.py`.
- `scoring_service.score_live_show(read_conn, live_conn, show_id)`:
  - load `live_songs` → `normalize_setlist`;
  - load `frozen_bracket`, `snapshots`;
  - derive `next_call_by_index`: for actual index `i>=1`, find the **LAST** snapshot (in append order) with `after_count == i` — corrections/set-advances create duplicates, and the last one is what was actually on screen when `actual[i]` revealed — and take its first remaining entry's `song_id`; no matching snapshot → omit the key (no-event, per Phase-1 semantics);
  - derive `early_called_indices` from earlier snapshots (song correctly placed when it was `after_count <= i-2`); optional for v1;
  - derive `bustout_song_ids` from `songs.is_bustout_placeholder` for the actual setlist's song_ids;
  - call `score_show`; return JSON (totals, per-song attributions with reason/beaten_claim, streak timeline, badges, bustouts, missed-pick list).
- Endpoint returns that JSON.
TDD: seed a live show + bracket + snapshots, hit the endpoint, assert totals match a Phase-1 fixture. Commit.

### Task 3.2: Corrections re-score cleanly

**Files:** test `api/tests/test_score_correction.py`.
- Because scoring is pure over stored JSON + current `live_songs`, a phish.net correction (via existing reconcile/`replace_song_at`) that appends a new snapshot + updates `live_songs` → the `/score` endpoint returns the corrected score with no extra code.
TDD: score, apply a correction (swap a song_id at a slot + append snapshot), re-score, assert the delta is exactly the corrected song's claim change. Commit.

---

## Phase 4 — Live scoreboard UI (own design pass)

> This phase gets a dedicated visual pass — invoke the **frontend-design skill** at its start. Keep the engine untouched; the UI only consumes `/score` events. Tasks here are coarser by design.

- **4.1 Data hook** — `web/` client hook polling/subscribing to `/live/show/{id}/score`; map attributions → event feed items.
- **4.2 Hero total + ledger split** — one big combined total that punches on change; secondary `🔮 · ⚡` readout. Ledger color identity (Foresight = indigo/crystal, Live = amber/lightning).
- **4.3 Next-song card flip** — the priority moment: face-up pending call → hit snap / miss deflate. Reuse `HitRankIndicator` bullseye as the "called it" glyph.
- **4.4 Combo meter** — understated at ×1, escalates at ×1.5/×2, weighty drain on reset.
- **4.5 Event feed with beaten-claim line** — `Tweezer — ⚡ NEXT-SONG ✓ +30 (beat 🔮 wrong-set +5)`; `🔭 called it early`; `↻ Corrected …`; `🎸 BUSTOUT` celebration; `✓ foreseen` beat.
- **4.6 Onboarding** — persistent framing header + first-event coach mark.
- Manual verification via the `verify`/`run` skill against a replayed show.

---

## Phase 5 — Post-show scorecard

- **5.1** Reuse `scoring_service` over the final setlist for a completed show; persist final totals + breakdown per show (extend `live_score_state` or a `scorecards` table).
- **5.2** Recap page: Foresight breakdown, Live breakdown, streak highlights, total, "songs that beat the app" list.
- **5.3** Cross-show "best yet?": headline raw total + secondary points-per-predictable-song. (Full history/leaderboard deferred.)
- TDD the persistence + selection; manual-verify the recap page.

---

## Sequencing & checkpoints

Phase 0 → 1 → 2 → 3 are backend and strictly ordered (each builds on the last). Phase 1 is the highest-value, fully TDD'd core — get it green and locked before touching storage. Phases 4–5 depend on 3. Commit after every green step; open a PR from `feat/scoring-game` after Phase 3 (a working, testable backend) for review before the UI pass.
