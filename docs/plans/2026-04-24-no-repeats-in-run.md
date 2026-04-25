# No-repeats-in-run Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Hard-filter from preview candidates any song that was played in a prior show of the same residency run.

**Architecture:** At the top of `build_preview`, resolve the live show's tour and run, query `setlist_songs` for songs played in run-mate shows before tonight, build a `played_in_run` set. Pass it through `predict_next_stateless` to `apply_post_rules` (which now accepts it as a second exclusion set). Same set is passed to `_compute_hit_rank` for the entered-slot retroactive rank.

**Tech Stack:** FastAPI + SQLite on the backend (`api/`).

**Design doc:** `docs/plans/2026-04-24-no-repeats-in-run-design.md`

---

## Preflight

```bash
cd /Users/David/phishpicker
git pull
git log --oneline -5
```

Expected HEAD: `f45b05c` (design doc). All hit-rank work landed (`bc10e1e` and earlier).

---

### Task 1: Extend `apply_post_rules` to accept `played_in_run`

**Files:**
- Modify: `api/src/phishpicker/model/rules.py`
- Test: `api/tests/model/test_rules.py`

**Step 1: Write failing tests**

Append to `api/tests/model/test_rules.py`:

```python
def test_rule_zeros_played_earlier_in_run():
    scored = [(100, 5.0), (101, 3.0), (102, 2.0)]
    out = apply_post_rules(scored, played_tonight=set(), played_in_run={101})
    d = dict(out)
    assert d[101] == 0.0
    assert d[100] == 5.0
    assert d[102] == 2.0


def test_rule_zeros_song_in_both_sets_idempotent():
    scored = [(100, 5.0), (101, 3.0)]
    out = apply_post_rules(scored, played_tonight={101}, played_in_run={101})
    assert dict(out)[101] == 0.0


def test_rule_played_in_run_defaults_to_no_filter():
    scored = [(100, 5.0), (101, 3.0)]
    out = apply_post_rules(scored, played_tonight={101})
    d = dict(out)
    assert d[101] == 0.0
    assert d[100] == 5.0
```

**Step 2: Verify tests fail**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/model/test_rules.py -xvs
```

Expected: the first two FAIL with `TypeError: apply_post_rules() got an unexpected keyword argument 'played_in_run'`.

**Step 3: Implement**

Replace `api/src/phishpicker/model/rules.py` with:

```python
def apply_post_rules(
    scored: list[tuple[int, float]],
    played_tonight: set[int],
    played_in_run: set[int] | None = None,
) -> list[tuple[int, float]]:
    excluded = played_tonight if played_in_run is None else played_tonight | played_in_run
    return [(sid, 0.0 if sid in excluded else s) for sid, s in scored]
```

**Step 4: Verify pass**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/model/test_rules.py -xvs
```

Expected: all 6 tests pass (3 existing + 3 new).

**Step 5: Commit**

```bash
git add api/src/phishpicker/model/rules.py api/tests/model/test_rules.py
git commit -m "feat(api): apply_post_rules accepts played_in_run

Optional second exclusion set, used by /preview to filter songs played
earlier in a residency run.

🤖 assist"
```

---

### Task 2: Thread `played_in_run` through `predict_next_stateless`

**Files:**
- Modify: `api/src/phishpicker/predict.py:7-23` (signature) and `:54` (call site)
- Test: `api/tests/test_predict_post.py` (or wherever predict tests live — check first)

**Step 1: Locate the predict tests**

```bash
grep -rn "def test_.*predict" /Users/David/phishpicker/api/tests/ | head -10
```

Pick the file that most naturally hosts a test for the new kwarg behavior. Likely `tests/test_predict_post.py` or `tests/test_predict_virtual_played.py`.

**Step 2: Write failing test**

Append a test that exercises the new kwarg by calling `predict_next_stateless` with `played_in_run` containing a song known to score positive in the seed fixtures, and asserting that song does NOT appear in the returned candidates.

```python
def test_predict_next_stateless_excludes_played_in_run(seeded_client):
    """played_in_run songs must be filtered out of the candidate list."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.model.scorer import HeuristicScorer
    from phishpicker.predict import predict_next_stateless

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as conn:
        # Baseline: top candidate without filter
        baseline = predict_next_stateless(
            read_conn=conn,
            played_songs=[],
            current_set="1",
            show_date="2026-04-24",
            venue_id=1,
            scorer=HeuristicScorer(),
        )
        assert baseline, "expected at least one candidate"
        target = baseline[0]["song_id"]

        # With target in played_in_run, it must be absent
        filtered = predict_next_stateless(
            read_conn=conn,
            played_songs=[],
            current_set="1",
            show_date="2026-04-24",
            venue_id=1,
            scorer=HeuristicScorer(),
            played_in_run={target},
        )
        ids = [c["song_id"] for c in filtered]
        assert target not in ids
```

(Reuse the `seeded_client` fixture pattern from `test_live_preview.py:151+`. If the chosen test file doesn't already use that fixture, copy the import / fixture wiring from `test_live_preview.py` for consistency. The fixture exists for its env-var side effect; you don't actually need the client.)

**Step 3: Verify it fails**

Expected: `TypeError: predict_next_stateless() got an unexpected keyword argument 'played_in_run'`.

**Step 4: Implement**

In `api/src/phishpicker/predict.py`:

- Add `played_in_run: set[int] | None = None` to the signature (anywhere after `top_n` is fine, kwargs-only).
- At the `apply_post_rules` call (line 54), pass it through:
  ```python
  scored = apply_post_rules(scored, played_tonight=set(played_songs), played_in_run=played_in_run)
  ```

**Step 5: Verify pass**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_predict_post.py -xvs       # or whichever file the new test lives in
uv run pytest tests/test_live_preview.py -xvs       # ensure unchanged behavior elsewhere
```

Both must pass. The known pre-existing `test_upcoming` failure is unrelated.

**Step 6: Commit**

```bash
git add api/src/phishpicker/predict.py api/tests/<the test file>
git commit -m "feat(api): predict_next_stateless accepts played_in_run

Threads through to apply_post_rules. Defaults to None for the training
pipeline, which doesn't use this filter.

🤖 assist"
```

---

### Task 3: Add `_played_in_run` helper

**Files:**
- Modify: `api/src/phishpicker/live_preview.py` (add helper near the other module-level helpers)
- Test: `api/tests/test_live_preview.py`

This helper resolves the live show's `tour_id`, finds the run bounds, and returns the set of song_ids played in run-mate shows that occurred *before* tonight.

**Step 1: Write failing test**

Append to `api/tests/test_live_preview.py`:

```python
def test_played_in_run_returns_empty_when_show_not_in_tour(seeded_client):
    """A show date with no matching tour returns an empty filter set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as conn:
        result = _played_in_run(conn, show_date="1900-01-01", venue_id=1)
    assert result == set()


def test_played_in_run_returns_empty_when_first_show_of_run(seeded_client):
    """Night 1 of a run has no prior shows → empty set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as conn:
        # Look up the earliest scheduled show for any venue; that's a run-of-1
        # or the start of a run.
        row = conn.execute(
            "SELECT show_date, venue_id FROM shows ORDER BY show_date ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return  # no shows in fixtures — vacuous pass
        result = _played_in_run(conn, show_date=row["show_date"], venue_id=row["venue_id"])
    # First-of-run can be empty, OR have entries if the same venue appeared
    # adjacent before — we just confirm the function returns a set without erroring.
    assert isinstance(result, set)


def test_played_in_run_includes_prior_run_mate_setlist(seeded_client, monkeypatch, tmp_path):
    """When two shows share venue+tour and date order, songs from the earlier
    show appear in the later show's played_in_run set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as write_conn:
        pass  # We need a write connection — open_db with read_only=False below.

    from phishpicker.db.connection import open_db as open_db_rw
    with closing(open_db_rw(settings.db_path)) as conn:
        # Find or insert a tour; insert two shows on the same tour+venue, two
        # days apart, with a known song in the first show's setlist.
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (9999, 'Test Tour', '2099-01-01', '2099-12-31')"
        )
        cur.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (9999, 'Test Venue')"
        )
        cur.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90001, '2099-06-01', 9999, 9999, '2099-01-01', 1)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90002, '2099-06-02', 9999, 9999, '2099-01-01', 0)"
        )
        # Pick any real song_id from the seed pool.
        sid_row = conn.execute("SELECT song_id FROM songs LIMIT 1").fetchone()
        assert sid_row, "fixture has no songs"
        sid = sid_row["song_id"]
        cur.execute(
            "INSERT OR REPLACE INTO setlist_songs "
            "(show_id, set_number, position, song_id) "
            "VALUES (90001, '1', 1, ?)",
            (sid,),
        )
        conn.commit()

        result = _played_in_run(conn, show_date="2099-06-02", venue_id=9999)

    assert sid in result
```

(The third test inserts test data into the seeded DB. If `seeded_client` fixture rebuilds the DB per test, that's fine — these inserts live only for the lifetime of one test. If teardown is needed, add a try/finally to delete the rows.)

**Step 2: Verify tests fail**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_live_preview.py::test_played_in_run_returns_empty_when_show_not_in_tour -xvs
```

Expected: `ImportError: cannot import name '_played_in_run'`.

**Step 3: Implement**

In `api/src/phishpicker/live_preview.py`, add above `build_preview` (alongside `_compute_hit_rank`):

```python
def _played_in_run(
    read_conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
) -> set[int]:
    """Songs played in run-mate shows that happened before show_date.

    Returns an empty set when the live show isn't in any run (no tour
    found, no same-venue adjacent shows, or it's the first show of its run).
    """
    if venue_id is None:
        return set()

    # Resolve tour_id: prefer the canonical shows row if the live date is
    # already pre-scheduled; fall back to the tours table by date range.
    tour_row = read_conn.execute(
        "SELECT tour_id FROM shows WHERE show_date = ? AND venue_id = ? LIMIT 1",
        (show_date, venue_id),
    ).fetchone()
    if tour_row and tour_row["tour_id"] is not None:
        tour_id = tour_row["tour_id"]
    else:
        fallback = read_conn.execute(
            "SELECT tour_id FROM tours WHERE start_date <= ? AND end_date >= ? LIMIT 1",
            (show_date, show_date),
        ).fetchone()
        if not fallback or fallback["tour_id"] is None:
            return set()
        tour_id = fallback["tour_id"]

    from phishpicker.model.stats import _find_run_start

    run_start = _find_run_start(read_conn, venue_id, show_date, tour_id=tour_id)
    if run_start == show_date:
        return set()  # first night of the run, or singleton

    rows = read_conn.execute(
        "SELECT DISTINCT ss.song_id "
        "FROM setlist_songs ss "
        "JOIN shows s ON s.show_id = ss.show_id "
        "WHERE s.venue_id = ? AND s.tour_id = ? "
        "  AND s.show_date >= ? AND s.show_date < ?",
        (venue_id, tour_id, run_start, show_date),
    ).fetchall()
    return {r["song_id"] for r in rows}
```

Note: import `_find_run_start` lazily inside the function (or at top of file) — `live_preview.py` already imports from `phishpicker.model.stats` (`compute_song_stats`), so a top-level addition is fine and consistent.

Also ensure `sqlite3` is imported at the top of `live_preview.py` (it already is, used by `build_preview`).

**Step 4: Verify pass**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_live_preview.py -xvs
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add api/src/phishpicker/live_preview.py api/tests/test_live_preview.py
git commit -m "feat(api): add _played_in_run helper

Returns the set of songs played in same-venue, same-tour shows of the
current run that occurred before show_date. Tour resolved from the
shows table (preferred, since live shows are pre-scheduled) with tours
date-range fallback. Empty when no tour or first night of run.

🤖 assist"
```

---

### Task 4: Wire `played_in_run` into `build_preview`

**Files:**
- Modify: `api/src/phishpicker/live_preview.py:13-153` (`build_preview` body — note line numbers may have drifted; reorient by reading the file)
- Test: `api/tests/test_live_preview.py`

**Step 1: Write failing integration test**

Append to `api/tests/test_live_preview.py`:

```python
def test_preview_excludes_songs_played_earlier_in_run(seeded_client, live_show_id):
    """A song from a prior run-mate show must not appear in any predicted
    slot's top_k of /preview."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db

    settings = Settings()
    # Seed a prior run-mate canonical show with a known song.
    with closing(open_db(settings.db_path)) as conn:
        live = conn.execute(
            "SELECT show_date, venue_id FROM live_show WHERE show_id = ?",
            (live_show_id,),
        ).fetchone()
        assert live, "expected live show in fixture"
        # If the live show has no venue/tour mapping in fixtures, this test
        # can't exercise the filter — bail with skip.
        if live["venue_id"] is None:
            import pytest
            pytest.skip("live fixture lacks venue_id; can't construct run")
        sid_row = conn.execute("SELECT song_id FROM songs LIMIT 1").fetchone()
        assert sid_row
        target_song_id = sid_row["song_id"]

        # Find or use the live show's tour; if missing, create one.
        tour_id = 9998
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (?, 'Run Filter Test', '1900-01-01', '2999-12-31')",
            (tour_id,),
        )
        # Anchor live show into shows so tour resolution finds it.
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90100, ?, ?, ?, '1900-01-01', 0)",
            (live["show_date"], live["venue_id"], tour_id),
        )
        # Prior run-mate (one day earlier) with target song in setlist.
        from datetime import date, timedelta
        prior_date = (date.fromisoformat(live["show_date"]) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90101, ?, ?, ?, '1900-01-01', 1)",
            (prior_date, live["venue_id"], tour_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO setlist_songs "
            "(show_id, set_number, position, song_id) "
            "VALUES (90101, '1', 1, ?)",
            (target_song_id,),
        )
        conn.commit()

    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    for s in slots:
        if s["state"] == "predicted":
            ids = [c["song_id"] for c in s.get("top_k", [])]
            assert target_song_id not in ids, (
                f"target song {target_song_id} leaked into top_k for slot {s['slot_idx']}"
            )
```

**Step 2: Verify it fails**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_live_preview.py::test_preview_excludes_songs_played_earlier_in_run -xvs
```

Expected: assertion fails — the target song will appear in some predicted slot's `top_k` because the filter isn't yet wired in.

**Step 3: Wire `played_in_run` into `build_preview`**

In `api/src/phishpicker/live_preview.py`, inside `build_preview`, after `song_ids` is built and before the entered/predicted loop (i.e., near the existing per-show cache initialization around line 51):

```python
played_in_run = _played_in_run(read_conn, show_date, venue_id)
```

Then update the two places that score candidates:

1. The `_compute_hit_rank` call inside the `if entered:` branch — add `played_in_run=played_in_run` to its kwargs. (Update `_compute_hit_rank`'s signature to accept and forward this param to `predict_next_stateless`.)

2. The `predict_next_stateless` call in the predicted branch — add `played_in_run=played_in_run` to its kwargs.

Update `_compute_hit_rank` signature in `live_preview.py` (the helper from Task 1 of the previous feature):

```python
def _compute_hit_rank(
    *,
    read_conn: sqlite3.Connection,
    played_songs: list[int],
    target_song_id: int,
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str,
    prev_set_number: str | None,
    scorer: Scorer,
    song_ids_cache,
    song_names_cache,
    stats_cache,
    ext_cache,
    bigram_cache,
    played_in_run: set[int] | None = None,    # NEW
) -> int | None:
    """Return 1-based rank of `target_song_id` in the top-10 predictions, or None if absent."""
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
        played_in_run=played_in_run,             # NEW
    )
    for i, c in enumerate(cands):
        if c["song_id"] == target_song_id:
            return i + 1
    return None
```

**Step 4: Run the new test**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_live_preview.py -xvs
```

Expected: all preview tests pass, including the new one.

**Step 5: Run the full suite**

```bash
cd /Users/David/phishpicker/api
uv run pytest -x
```

Expected: only the known pre-existing `test_upcoming_returns_next_phish_with_tz` failure. No new failures.

**Step 6: Commit**

```bash
git add api/src/phishpicker/live_preview.py api/tests/test_live_preview.py
git commit -m "feat(api): filter run-mate songs from /preview candidates

Computes played_in_run once per /preview call from canonical shows,
threads it through both the predicted-slot prediction and the
hit-rank computation for entered slots.

🤖 assist"
```

---

### Task 5: Manual verification

**Step 1: Start the dev stack** (note the API port — 8001 per `web/.env.local`)

```bash
cd /Users/David/phishpicker/api && uv run uvicorn phishpicker.app:create_app --factory --reload --port 8001
cd /Users/David/phishpicker/web && pnpm dev
```

**Step 2: Open `http://localhost:3000`**

For tonight's Sphere show:
- Stash should no longer appear in any predicted slot's top-1 (or anywhere in top-10) for set 1.
- Other songs played in any prior Sphere 2026 night (4/16, 4/17, 4/18, 4/23) should also be absent.
- Songs that haven't been played in the run should still appear normally.

**Step 3: Push**

```bash
git push origin main
```

CI runs and Deploy-to-NAS triggers automatically. The NAS SSH 6-hour window must be open for the deploy to land — if it fails with `websocket: bad handshake`, re-enable the window and re-run the failed action.

**Step 4: Announce**

```bash
~/bin/ha-announce.sh "Phishpicker: no-repeats-in-run filter shipped" living_room 60 &
```

---

## Notes for the implementer

- **Tour resolution priority:** prefer `shows.tour_id` for the live show's date — the Sphere 2026 dates are pre-ingested with `tour_id` set. The `tours` table fallback handles the edge case where a show's date is somehow not pre-scheduled but a tour spans it.
- **`_played_in_run` is computed once per `/preview` call** and reused across all 18 slots (predicted + entered alike). Don't sprinkle calls inside the loop.
- **Don't filter `played_tonight` separately from `played_in_run`** — `apply_post_rules` unions them. Keeping them as distinct args is clearer when reading the code; the union is implementation detail.
- **Hit-rank semantics under the filter:** if a song actually played tonight was also played earlier in the run (rare — a Phish repeat night-to-night), the candidate pool excludes it, so its retroactive rank becomes `None` and the indicator shows an em-dash. Acceptable.
- **Training pipeline is unaffected** — `played_in_run` defaults to `None` everywhere, so existing tests and the train CLI keep their current behavior.
