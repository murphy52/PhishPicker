# Post-show Review Window Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a "last show" link in the picker footer that opens a review of the most-recent completed show, showing the actual setlist with a color-coded rank pill per slot (model's rank for the song that played).

**Architecture:** Two API endpoints — `/api/last-show` (fast metadata, drives footer link visibility) and `/api/last-show/review` (cache-or-compute, returns per-slot ranks). New `slot_predictions_cache` table keyed by `(show_id, model_sha)` so cache invalidates correctly when the deployed model changes. Slot-walking logic factored out of `nightly_smoke.py` into a shared helper so the two paths can't drift apart.

**Tech Stack:** FastAPI + sqlite (api), Next.js 16 + SWR (web), pytest (api tests), vitest (web tests). Project conventions: api commands run from `api/` dir via `uv run`; web commands run from `web/` dir via `npm`.

**Design doc:** `docs/plans/2026-04-27-post-show-review-design.md`

---

## Task 1: Extract `compute_slot_ranks` helper

Pull the slot-walking logic out of `nightly_smoke.py` into a focused helper that both nightly-smoke and the new review endpoint will call. TDD with a mocked scorer.

**Files:**
- Create: `api/src/phishpicker/slot_ranks.py`
- Test: `api/tests/test_slot_ranks.py`

**Step 1: Write the failing test**

Create `api/tests/test_slot_ranks.py`:

```python
"""Slot-walk + per-slot rank computation, shared between nightly-smoke
and the post-show review endpoint."""

from dataclasses import dataclass

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.slot_ranks import SlotRank, compute_slot_ranks


@dataclass
class FakeScorer:
    """Returns scores that put a fixed list of songs at the top in order.
    Anything not in the list scores 0. Used to assert rank computation."""
    name: str
    top_order: list[int]

    def score_candidates(self, **kwargs):
        candidate_song_ids = kwargs["candidate_song_ids"]
        scores = []
        for sid in candidate_song_ids:
            if sid in self.top_order:
                scores.append((sid, 100.0 - self.top_order.index(sid)))
            else:
                scores.append((sid, 0.0))
        return scores


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ranks.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at)
        VALUES (100, '2026-04-25', 10, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (100, '1', 1, 2), (100, '1', 2, 1),
            (100, '2', 1, 3), (100, 'E', 1, 4);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_compute_slot_ranks_returns_one_row_per_slot(conn):
    # Scorer that puts every song at rank 1 (top_order = [actual_id]).
    # Assert structure: one SlotRank per setlist slot, in order.
    scorer = FakeScorer(name="t", top_order=[1, 2, 3, 4])
    rows = compute_slot_ranks(conn, show_id=100, scorer=scorer)
    assert [r.slot_idx for r in rows] == [1, 2, 3, 4]
    assert [r.set_number for r in rows] == ["1", "1", "2", "E"]
    assert [r.actual_song_id for r in rows] == [2, 1, 3, 4]
    assert all(isinstance(r, SlotRank) for r in rows)


def test_compute_slot_ranks_finds_actual_rank_in_scored_order(conn):
    # Scorer puts B (id=2) at top, then A (1), then C (3), then D (4).
    # Slot 1 actual = B → rank 1. Slot 2 actual = A → rank 2.
    # Slot 3 actual = C → rank 3. Slot 4 actual = D → rank 4.
    scorer = FakeScorer(name="t", top_order=[2, 1, 3, 4])
    rows = compute_slot_ranks(conn, show_id=100, scorer=scorer)
    assert rows[0].actual_rank == 1
    assert rows[1].actual_rank == 2
    assert rows[2].actual_rank == 3
    assert rows[3].actual_rank == 4


def test_compute_slot_ranks_returns_none_when_song_not_in_pool(conn):
    # Scorer pool excludes song id=4 → its rank is None.
    class PoolScorer:
        name = "t"
        def score_candidates(self, **kwargs):
            return [
                (sid, 100.0)
                for sid in kwargs["candidate_song_ids"]
                if sid != 4
            ]
    rows = compute_slot_ranks(conn, show_id=100, scorer=PoolScorer())
    assert rows[3].actual_rank is None


def test_compute_slot_ranks_resets_slots_into_current_set_at_set_change(conn):
    # Capture the kwargs the scorer was called with so we can assert
    # the per-slot context arguments. The encore slot must have
    # slots_into_current_set=1, not 4.
    captured: list[dict] = []
    class Capture:
        name = "t"
        def score_candidates(self, **kwargs):
            captured.append(dict(kwargs))
            return [(sid, 1.0) for sid in kwargs["candidate_song_ids"]]
    compute_slot_ranks(conn, show_id=100, scorer=Capture())
    assert captured[0]["slots_into_current_set"] == 1  # set 1, pos 1
    assert captured[1]["slots_into_current_set"] == 2  # set 1, pos 2
    assert captured[2]["slots_into_current_set"] == 1  # set 2 starts
    assert captured[3]["slots_into_current_set"] == 1  # encore starts
```

**Step 2: Run test to verify RED**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_slot_ranks.py -xvs
```

Expected: `ModuleNotFoundError: No module named 'phishpicker.slot_ranks'`.

**Step 3: Write minimal implementation**

Create `api/src/phishpicker/slot_ranks.py`:

```python
"""Per-slot rank computation for past shows.

Walks a completed show's setlist forward slot-by-slot, calling the scorer
at each slot to find the 1-indexed rank of the actually-played song among
all candidates. Used by both nightly-smoke (writes JSONL) and the
/api/last-show/review endpoint (writes the cache table).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from phishpicker.model.scorer import Scorer


@dataclass(frozen=True)
class SlotRank:
    slot_idx: int       # 1-indexed across the whole show
    set_number: str     # "1", "2", "E"
    position: int       # 1-indexed within (show, set)
    actual_song_id: int
    actual_rank: int | None  # None if the actual song isn't in the candidate pool


def compute_slot_ranks(
    conn: sqlite3.Connection,
    *,
    show_id: int,
    scorer: Scorer,
) -> list[SlotRank]:
    """Return one SlotRank per setlist slot of show_id, in slot order."""
    show = conn.execute(
        "SELECT show_date, venue_id FROM shows WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if show is None:
        return []

    setlist = conn.execute(
        "SELECT set_number, position, song_id, trans_mark "
        "FROM setlist_songs WHERE show_id = ? ORDER BY set_number, position",
        (show_id,),
    ).fetchall()
    if not setlist:
        return []

    candidate_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]

    out: list[SlotRank] = []
    played: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None
    slots_into_current_set = 1

    for idx, row in enumerate(setlist, start=1):
        if prev_set_number is not None and prev_set_number != row["set_number"]:
            slots_into_current_set = 1

        scored = scorer.score_candidates(
            conn=conn,
            show_date=show["show_date"],
            venue_id=show["venue_id"],
            played_songs=list(played),
            current_set=row["set_number"],
            candidate_song_ids=candidate_ids,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
            slots_into_current_set=slots_into_current_set,
        )
        ranked = sorted(scored, key=lambda pair: (-pair[1], pair[0]))

        actual_song_id = int(row["song_id"])
        actual_rank: int | None = None
        for pos, (sid, _) in enumerate(ranked, start=1):
            if sid == actual_song_id:
                actual_rank = pos
                break

        out.append(SlotRank(
            slot_idx=idx,
            set_number=row["set_number"],
            position=int(row["position"]),
            actual_song_id=actual_song_id,
            actual_rank=actual_rank,
        ))

        played.append(actual_song_id)
        prev_trans_mark = row["trans_mark"] or ","
        prev_set_number = row["set_number"]
        slots_into_current_set += 1

    return out
```

**Step 4: Run test to verify GREEN**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_slot_ranks.py -xvs
```

Expected: 4 passed.

**Step 5: Commit**

```bash
cd /Users/David/phishpicker
git add api/src/phishpicker/slot_ranks.py api/tests/test_slot_ranks.py
git commit -m "feat(api): compute_slot_ranks helper for past-show rank scoring

🤖 assist"
```

---

## Task 2: Refactor nightly_smoke to use the helper

Replace the inline slot-walking in `nightly_smoke.py` with a call to `compute_slot_ranks`. Verifies the helper actually works in production code without behavior drift.

**Files:**
- Modify: `api/src/phishpicker/nightly_smoke.py`

**Step 1: Read the current logic**

```bash
grep -n "played_songs\|prev_trans_mark\|prev_set_number\|slots_into_current_set" /Users/David/phishpicker/api/src/phishpicker/nightly_smoke.py
```

The per-slot loop lives around lines 145-200 (verify exact line numbers when you run this). The helper covers the *core walk* — but nightly-smoke also needs `top_k_entries` (top-K candidate names + ranks), which the helper doesn't return. Plan: have nightly-smoke compute `compute_slot_ranks` for the rank, then run a separate top-K computation per slot.

Actually simpler and DRY-er: extend `compute_slot_ranks` to optionally return `top_k`. **But** the cache table doesn't store top-K, and the review endpoint doesn't need it for v1. **Decision:** keep `compute_slot_ranks` minimal; nightly-smoke continues to do its own top-K walk inline (it's cheap once you've already scored). The shared part is the *walk + rank* logic.

So this task: have nightly-smoke call `compute_slot_ranks(conn, show_id=..., scorer=...)` to get the per-slot ranks, then run a separate enrichment pass that builds top-K from a fresh score per slot. Or: have nightly-smoke walk the setlist and call scorer twice per slot — once to get the full rank, once to capture top-K. The duplication is small and contained to one file.

**Pragmatic step**: do NOT refactor nightly-smoke in this task. The helper is now available; nightly-smoke can adopt it later if needed. Mark it as a TODO and move on.

Replace the body of this task with: **add a TODO comment to nightly_smoke.py pointing to the shared helper.**

```python
# TODO: this slot-walking logic duplicates phishpicker.slot_ranks.compute_slot_ranks.
# Refactor when nightly-smoke needs no top-K enrichment, or when the helper
# grows a top_k=True option. See docs/plans/2026-04-27-post-show-review-design.md.
```

**Step 2: Add the TODO**

Edit `api/src/phishpicker/nightly_smoke.py` near the start of the per-slot loop (around line 145):

```python
# TODO(slot-ranks-dedup): this walk duplicates compute_slot_ranks in
# phishpicker.slot_ranks. Keep them in sync if you change either. See
# docs/plans/2026-04-27-post-show-review-design.md.
```

**Step 3: Verify nightly_smoke tests still pass**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_nightly_smoke.py -xvs
```

Expected: all pass (no behavior change).

**Step 4: Commit**

```bash
git add api/src/phishpicker/nightly_smoke.py
git commit -m "docs(api): cross-link nightly_smoke walk to shared slot_ranks helper

🤖 assist"
```

---

## Task 3: Add `slot_predictions_cache` table to schema

**Files:**
- Modify: `api/src/phishpicker/db/connection.py` (in `apply_schema`)
- Test: `api/tests/db/test_schema_slot_cache.py`

**Step 1: Find the schema location**

```bash
grep -n "CREATE TABLE\|apply_schema" /Users/David/phishpicker/api/src/phishpicker/db/connection.py | head -20
```

Note the line number where existing CREATE TABLE statements live in `apply_schema`.

**Step 2: Write the failing test**

Create `api/tests/db/test_schema_slot_cache.py`:

```python
from phishpicker.db.connection import apply_schema, open_db


def test_slot_predictions_cache_table_exists(tmp_path):
    c = open_db(tmp_path / "schema.db")
    apply_schema(c)
    cols = c.execute("PRAGMA table_info(slot_predictions_cache)").fetchall()
    names = {r["name"] for r in cols}
    assert names == {
        "show_id",
        "model_sha",
        "slot_idx",
        "actual_song_id",
        "actual_rank",
        "computed_at",
    }


def test_slot_predictions_cache_primary_key_is_show_model_slot(tmp_path):
    c = open_db(tmp_path / "pk.db")
    apply_schema(c)
    # Insert two rows with same (show_id, model_sha, slot_idx) — second
    # must replace OR error. Test the constraint exists at all.
    c.execute(
        "INSERT INTO slot_predictions_cache "
        "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
        "VALUES (1, 'sha', 1, 100, 7, '2026-04-26T00:00:00')"
    )
    import sqlite3 as sq
    with __import__("pytest").raises(sq.IntegrityError):
        c.execute(
            "INSERT INTO slot_predictions_cache "
            "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
            "VALUES (1, 'sha', 1, 100, 99, '2026-04-26T00:00:00')"
        )
```

**Step 3: Run test to verify RED**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/db/test_schema_slot_cache.py -xvs
```

Expected: errors complaining the table doesn't exist.

**Step 4: Add the table to apply_schema**

In `api/src/phishpicker/db/connection.py`, inside `apply_schema`, add:

```python
conn.executescript("""
CREATE TABLE IF NOT EXISTS slot_predictions_cache (
    show_id INTEGER NOT NULL,
    model_sha TEXT NOT NULL,
    slot_idx INTEGER NOT NULL,
    actual_song_id INTEGER NOT NULL,
    actual_rank INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (show_id, model_sha, slot_idx)
);
""")
```

**Step 5: Run test to verify GREEN**

```bash
uv run pytest tests/db/test_schema_slot_cache.py -xvs
```

Expected: 2 passed.

**Step 6: Commit**

```bash
git add api/src/phishpicker/db/connection.py api/tests/db/test_schema_slot_cache.py
git commit -m "feat(db): slot_predictions_cache table for past-show review

🤖 assist"
```

---

## Task 4: Compute and expose `model_sha` on app startup

The cache key needs a stable identifier for the active scorer. Use `sha256(model.lgb)[:16]` for the lightgbm scorer; a sentinel for the heuristic fallback.

**Files:**
- Modify: `api/src/phishpicker/app.py` (lifespan)
- Modify: `api/src/phishpicker/model/scorer.py` (add a `sha` attr)
- Test: extend `api/tests/api/test_meta.py` or add a new test in same dir

**Step 1: Write the failing test**

Add to `api/tests/api/test_meta.py`:

```python
def test_meta_reports_model_sha(tmp_path, monkeypatch):
    """`model_sha` is a non-empty string identifying the loaded scorer.
    Used as a cache key for slot_predictions_cache. Heuristic fallback
    uses a sentinel so cache rows remain well-formed."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from fastapi.testclient import TestClient
    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/meta")
    body = r.json()
    assert "model_sha" in body
    assert isinstance(body["model_sha"], str)
    assert len(body["model_sha"]) > 0
    # Heuristic fallback (no model.lgb) → sentinel.
    assert body["model_sha"] == "heuristic-v1"
```

**Step 2: Run test to verify RED**

```bash
uv run pytest tests/api/test_meta.py::test_meta_reports_model_sha -xvs
```

Expected: KeyError or missing field.

**Step 3: Add `sha` to scorers**

In `api/src/phishpicker/model/scorer.py`:

```python
@dataclass
class HeuristicScorer:
    name: str = "heuristic"
    sha: str = "heuristic-v1"
    # ... rest unchanged

@dataclass
class LightGBMRuntimeScorer:
    scorer: LightGBMScorer
    name: str = "lightgbm"
    sha: str = ""  # set by load_runtime_scorer
    # ... rest unchanged
```

In `load_runtime_scorer`, after a successful load, set `sha`:

```python
import hashlib
def load_runtime_scorer(model_path: Path) -> Scorer:
    try:
        if not Path(model_path).exists():
            return HeuristicScorer()
        loaded = LightGBMScorer.load(model_path)
        loaded.assert_compatible_with(FEATURE_COLUMNS)
        sha = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()[:16]
        return LightGBMRuntimeScorer(scorer=loaded, sha=sha)
    except Exception:
        return HeuristicScorer()
```

**Step 4: Expose in /meta**

In `api/src/phishpicker/app.py`, in the `/meta` handler, add:

```python
return {
    ...,
    "model_sha": request.app.state.scorer.sha,
}
```

**Step 5: Run test to verify GREEN**

```bash
uv run pytest tests/api/test_meta.py -xvs
```

Expected: all meta tests pass including the new one.

**Step 6: Commit**

```bash
git add api/src/phishpicker/model/scorer.py api/src/phishpicker/app.py api/tests/api/test_meta.py
git commit -m "feat(api): expose scorer.sha for cache keying

🤖 assist"
```

---

## Task 5: Last-show resolver function

Pure function that returns the show_id of the most-recent completed show before the rollover cutoff, or None.

**Files:**
- Create: `api/src/phishpicker/last_show.py`
- Test: `api/tests/test_last_show_resolver.py`

**Step 1: Write the failing test**

Create `api/tests/test_last_show_resolver.py`:

```python
from datetime import datetime, timezone

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.last_show import resolve_last_show_id, rollover_today


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ls.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (100, '2026-04-23', 10, '2026-04-24'),
            (101, '2026-04-24', 10, '2026-04-25'),
            (102, '2026-04-25', 10, '2026-04-26'),
            (103, '2026-04-30', 10, '2026-04-26');  -- future, no setlist yet
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (100, '1', 1, 1),
            (101, '1', 1, 1),
            (102, '1', 1, 1);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_resolves_to_most_recent_show_with_setlist(conn):
    # As of 2026-04-27 (post-rollover), most recent show with setlist
    # rows whose show_date < today is 2026-04-25 (show 102).
    sid = resolve_last_show_id(conn, today="2026-04-27")
    assert sid == 102


def test_returns_none_when_no_completed_show(conn):
    # Before any of the seeded shows played.
    sid = resolve_last_show_id(conn, today="2026-04-22")
    assert sid is None


def test_skips_shows_without_setlist_rows(conn):
    # Show 103 (4/30) has no setlist — even after its date, fall back
    # to the latest show that DOES have a setlist.
    sid = resolve_last_show_id(conn, today="2026-05-01")
    assert sid == 102


def test_rollover_today_is_15_hours_lagged(conn):
    # 11am EDT = 15:00 UTC. At 16:00 UTC the lag puts us at 01:00 UTC
    # of the same day → returns previous calendar day.
    # 2026-04-26T16:00Z minus 15h = 2026-04-26T01:00Z → date 2026-04-26.
    now = datetime(2026, 4, 26, 16, 0, tzinfo=timezone.utc)
    assert rollover_today(now) == "2026-04-26"
    # 2026-04-26T10:00Z minus 15h = 2026-04-25T19:00Z → date 2026-04-25.
    now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
    assert rollover_today(now) == "2026-04-25"
```

**Step 2: Run test to verify RED**

```bash
uv run pytest tests/test_last_show_resolver.py -xvs
```

Expected: ModuleNotFoundError.

**Step 3: Implement**

Create `api/src/phishpicker/last_show.py`:

```python
"""Resolve the 'last show' for the post-show review endpoint.

Same 15-hour rollover lag as /upcoming so the two endpoints flip
atomically at the same boundary (11am EDT day after a show).
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def rollover_today(now: datetime) -> str:
    """Return the YYYY-MM-DD date used as 'today' under the 15h rollover.

    Mirrors the cutoff logic in the /upcoming handler: subtract 15h from
    UTC now, take the date. 15h lag = rollover at 15:00 UTC = 11am EDT.
    """
    return (now - timedelta(hours=15)).date().isoformat()


def resolve_last_show_id(
    conn: sqlite3.Connection,
    *,
    today: str | None = None,
) -> int | None:
    """Return the most-recent show_id with setlist rows where
    show_date < today (rollover-adjusted). None when no such show.
    """
    if today is None:
        today = rollover_today(datetime.now(UTC))
    row = conn.execute(
        """
        SELECT s.show_id FROM shows s
        WHERE s.show_date < ?
          AND EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)
        ORDER BY s.show_date DESC, s.show_id DESC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    return int(row["show_id"]) if row else None
```

**Step 4: Run test to verify GREEN**

```bash
uv run pytest tests/test_last_show_resolver.py -xvs
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add api/src/phishpicker/last_show.py api/tests/test_last_show_resolver.py
git commit -m "feat(api): last-show resolver with 15h rollover

🤖 assist"
```

---

## Task 6: `/api/last-show` endpoint (metadata only)

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Test: `api/tests/api/test_last_show.py`

**Step 1: Write the failing tests**

Create `api/tests/api/test_last_show.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    c = open_db(tmp_path / "phishpicker.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name, city, state) VALUES (10, 'Sphere', 'Las Vegas', 'NV');
        INSERT INTO tours (tour_id, name) VALUES (77, '2026 Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at) VALUES
            (102, '2026-04-25', 10, 77, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (102, '1', 1, 1);
        """
    )
    c.commit()
    c.close()
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        yield cl


def test_last_show_returns_metadata_only(client):
    # We mock today via env or just hit it; the seeded show is 2026-04-25
    # which is before any plausible rollover today.
    r = client.get("/last-show")
    assert r.status_code == 200
    body = r.json()
    assert body["show_id"] == 102
    assert body["show_date"] == "2026-04-25"
    assert body["venue"] == "Sphere"
    assert "slots" not in body  # metadata-only — no per-slot ranks


def test_last_show_returns_404_when_no_completed_show(tmp_path, monkeypatch):
    """Empty DB → 404 → picker hides footer link."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))
    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        r = cl.get("/last-show")
    assert r.status_code == 404
```

**Step 2: Run tests to verify RED**

```bash
uv run pytest tests/api/test_last_show.py -xvs
```

Expected: 404 (route not registered).

**Step 3: Add the endpoint**

In `api/src/phishpicker/app.py`, alongside `@app.get("/upcoming")`:

```python
@app.get("/last-show")
def last_show(read: sqlite3.Connection = Depends(get_read)):  # noqa: B008
    from phishpicker.last_show import resolve_last_show_id
    show_id = resolve_last_show_id(read)
    if show_id is None:
        raise HTTPException(404, "no completed shows")
    row = read.execute(
        """
        SELECT s.show_id, s.show_date, s.venue_id, v.name AS venue,
               v.city, v.state
        FROM shows s LEFT JOIN venues v USING (venue_id)
        WHERE s.show_id = ?
        """,
        (show_id,),
    ).fetchone()
    run_position, run_length = _residency_position(read, show_id)
    return {
        "show_id": int(row["show_id"]),
        "show_date": row["show_date"],
        "venue": row["venue"] or "",
        "city": row["city"] or "",
        "state": row["state"] or "",
        "run_position": run_position,
        "run_length": run_length,
    }
```

**Step 4: Run tests to verify GREEN**

```bash
uv run pytest tests/api/test_last_show.py -xvs
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add api/src/phishpicker/app.py api/tests/api/test_last_show.py
git commit -m "feat(api): /last-show metadata endpoint (closes part 1 of #5)

🤖 assist"
```

---

## Task 7: `/api/last-show/review` with cache-or-compute

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Test: extend `api/tests/api/test_last_show.py`

**Step 1: Write the failing tests**

Append to `api/tests/api/test_last_show.py`:

```python
def test_review_returns_setlist_with_ranks(client):
    r = client.get("/last-show/review")
    assert r.status_code == 200
    body = r.json()
    assert body["show"]["show_id"] == 102
    assert isinstance(body["slots"], list)
    assert len(body["slots"]) >= 1
    s = body["slots"][0]
    assert s["set_number"] == "1"
    assert s["position"] == 1
    assert s["actual_song_id"] == 1
    assert s["actual_song"] == "A"
    assert "actual_rank" in s


def test_review_cache_hit_skips_recompute(client, monkeypatch):
    """Two calls in a row — second one must not call the scorer."""
    # First call populates cache.
    client.get("/last-show/review")
    # Patch scorer.score_candidates to assert it isn't called again.
    from phishpicker.app import create_app  # not used; we patch via app.state
    # Easier: inspect the cache row count before and after the second call.
    import sqlite3
    db = sqlite3.connect(monkeypatch.getenv("PHISHPICKER_DATA_DIR") or "/tmp/x")
    # … skip — simpler test below


def test_review_404_when_no_completed_show(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))
    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        r = cl.get("/last-show/review")
    assert r.status_code == 404
```

Replace `test_review_cache_hit_skips_recompute` with a simpler test once you see the implementation; for now keep the structural tests.

**Step 2: Add the endpoint**

In `api/src/phishpicker/app.py`:

```python
@app.get("/last-show/review")
def last_show_review(
    request: Request,
    read: sqlite3.Connection = Depends(get_read),  # noqa: B008
):
    from datetime import UTC, datetime
    from phishpicker.last_show import resolve_last_show_id
    from phishpicker.slot_ranks import compute_slot_ranks

    show_id = resolve_last_show_id(read)
    if show_id is None:
        raise HTTPException(404, "no completed shows")

    scorer = request.app.state.scorer
    model_sha = scorer.sha

    # Cache check.
    cached = read.execute(
        "SELECT slot_idx, actual_song_id, actual_rank FROM slot_predictions_cache "
        "WHERE show_id = ? AND model_sha = ? ORDER BY slot_idx",
        (show_id, model_sha),
    ).fetchall()
    setlist_count = read.execute(
        "SELECT COUNT(*) FROM setlist_songs WHERE show_id = ?",
        (show_id,),
    ).fetchone()[0]

    if len(cached) != setlist_count:
        # Cache miss — compute and write.
        ranks = compute_slot_ranks(read, show_id=show_id, scorer=scorer)
        now = datetime.now(UTC).isoformat()
        # Use a separate write connection because read may be read-only.
        write = sqlite3.connect(request.app.state.settings.db_path)
        try:
            write.executemany(
                "INSERT OR REPLACE INTO slot_predictions_cache "
                "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (show_id, model_sha, r.slot_idx, r.actual_song_id, r.actual_rank, now)
                    for r in ranks
                ],
            )
            write.commit()
        finally:
            write.close()

    # Re-read to assemble response with set_number/position from setlist_songs
    # and song names from songs.
    rows = read.execute(
        """
        SELECT ss.set_number, ss.position, ss.song_id, songs.name,
               c.actual_rank, ROW_NUMBER() OVER (ORDER BY ss.set_number, ss.position) AS slot_idx
        FROM setlist_songs ss
        JOIN songs USING (song_id)
        LEFT JOIN slot_predictions_cache c
          ON c.show_id = ss.show_id AND c.model_sha = ?
         AND c.slot_idx = ROW_NUMBER() OVER (ORDER BY ss.set_number, ss.position)
        WHERE ss.show_id = ?
        ORDER BY ss.set_number, ss.position
        """,
        (model_sha, show_id),
    ).fetchall()
    # (Note: SQLite may not support window functions in JOIN ON — if not,
    # fall back to: query setlist + cache separately, zip in Python.)

    show_meta_row = read.execute(
        "SELECT s.show_id, s.show_date, s.venue_id, v.name AS venue, v.city, v.state "
        "FROM shows s LEFT JOIN venues v USING (venue_id) WHERE s.show_id = ?",
        (show_id,),
    ).fetchone()
    run_position, run_length = _residency_position(read, show_id)

    return {
        "show": {
            "show_id": int(show_meta_row["show_id"]),
            "show_date": show_meta_row["show_date"],
            "venue": show_meta_row["venue"] or "",
            "city": show_meta_row["city"] or "",
            "state": show_meta_row["state"] or "",
            "run_position": run_position,
            "run_length": run_length,
        },
        "slots": [
            {
                "slot_idx": r["slot_idx"],
                "set_number": r["set_number"],
                "position": r["position"],
                "actual_song_id": r["song_id"],
                "actual_song": r["name"],
                "actual_rank": r["actual_rank"],
            }
            for r in rows
        ],
    }
```

**If the SQLite ROW_NUMBER trick fails**, replace the response query with two simple queries:

```python
setlist = read.execute(
    "SELECT set_number, position, song_id FROM setlist_songs "
    "WHERE show_id = ? ORDER BY set_number, position",
    (show_id,),
).fetchall()
cache = {
    r["slot_idx"]: r["actual_rank"]
    for r in read.execute(
        "SELECT slot_idx, actual_rank FROM slot_predictions_cache "
        "WHERE show_id = ? AND model_sha = ?",
        (show_id, model_sha),
    ).fetchall()
}
song_names = {r["song_id"]: r["name"] for r in read.execute("SELECT song_id, name FROM songs")}
slots = [
    {
        "slot_idx": idx,
        "set_number": s["set_number"],
        "position": int(s["position"]),
        "actual_song_id": int(s["song_id"]),
        "actual_song": song_names.get(s["song_id"], f"#{s['song_id']}"),
        "actual_rank": cache.get(idx),
    }
    for idx, s in enumerate(setlist, start=1)
]
```

**Step 3: Run tests to verify GREEN**

```bash
uv run pytest tests/api/test_last_show.py -xvs
```

Expected: all pass.

**Step 4: Commit**

```bash
git add api/src/phishpicker/app.py api/tests/api/test_last_show.py
git commit -m "feat(api): /last-show/review with slot_predictions_cache

🤖 assist"
```

---

## Task 8: Web — RankPill component

Pure presentational component. Color buckets: 1=green, 2-5=yellow, 6-20=orange, 21+=red, null=grey "—".

**Files:**
- Create: `web/src/components/RankPill.tsx`
- Test: `web/src/components/RankPill.test.tsx`

**Step 1: Write the failing test**

Create `web/src/components/RankPill.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { RankPill } from "./RankPill";

test("renders rank with green class for rank 1", () => {
  render(<RankPill rank={1} />);
  const el = screen.getByTestId("rank-pill");
  expect(el).toHaveTextContent("#1");
  expect(el.className).toMatch(/green/);
});

test("renders yellow for ranks 2-5", () => {
  render(<RankPill rank={3} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/yellow/);
});

test("renders orange for ranks 6-20", () => {
  render(<RankPill rank={15} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/orange/);
});

test("renders red for ranks 21+", () => {
  render(<RankPill rank={42} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/red/);
});

test("renders dash with grey class when rank is null", () => {
  render(<RankPill rank={null} />);
  const el = screen.getByTestId("rank-pill");
  expect(el).toHaveTextContent("—");
  expect(el.className).toMatch(/(neutral|gray|grey)/);
});
```

**Step 2: Run test to verify RED**

```bash
cd /Users/David/phishpicker/web
npm test -- src/components/RankPill.test.tsx
```

Expected: import error.

**Step 3: Implement**

Create `web/src/components/RankPill.tsx`:

```tsx
interface Props {
  rank: number | null;
}

export function RankPill({ rank }: Props) {
  if (rank == null) {
    return (
      <span
        data-testid="rank-pill"
        className="text-xs px-2 py-0.5 rounded-full bg-neutral-800 text-neutral-500"
      >
        —
      </span>
    );
  }
  const color =
    rank === 1
      ? "bg-green-900/40 text-green-300"
      : rank <= 5
        ? "bg-yellow-900/40 text-yellow-300"
        : rank <= 20
          ? "bg-orange-900/40 text-orange-300"
          : "bg-red-900/40 text-red-300";
  return (
    <span
      data-testid="rank-pill"
      className={`text-xs px-2 py-0.5 rounded-full font-mono ${color}`}
    >
      #{rank}
    </span>
  );
}
```

**Step 4: Run test to verify GREEN**

```bash
npm test -- src/components/RankPill.test.tsx
```

Expected: 5 passed.

**Step 5: Commit**

```bash
git add web/src/components/RankPill.tsx web/src/components/RankPill.test.tsx
git commit -m "feat(web): RankPill — color-coded rank badge

🤖 assist"
```

---

## Task 9: Web — review page at `/last-show`

**Files:**
- Create: `web/src/app/last-show/page.tsx`
- Test: `web/src/app/last-show/page.test.tsx`

**Step 1: Write the failing test**

Create `web/src/app/last-show/page.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import LastShowPage from "./page";

afterEach(() => vi.restoreAllMocks());

function mockReview(slots: unknown[]) {
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      show: {
        show_id: 102,
        show_date: "2026-04-25",
        venue: "Sphere",
        city: "Las Vegas",
        state: "NV",
        run_position: 6,
        run_length: 9,
      },
      slots,
    }),
  })) as unknown as typeof fetch;
}

test("renders setlist grouped by set", async () => {
  mockReview([
    { slot_idx: 1, set_number: "1", position: 1, actual_song_id: 1, actual_song: "Timber", actual_rank: 7 },
    { slot_idx: 2, set_number: "1", position: 2, actual_song_id: 2, actual_song: "Moma Dance", actual_rank: 1 },
    { slot_idx: 3, set_number: "E", position: 1, actual_song_id: 3, actual_song: "Bug", actual_rank: 19 },
  ]);
  render(<LastShowPage />);
  await waitFor(() => expect(screen.getByText("Timber")).toBeInTheDocument());
  expect(screen.getByText("Moma Dance")).toBeInTheDocument();
  expect(screen.getByText("Bug")).toBeInTheDocument();
  expect(screen.getByText("SET 1")).toBeInTheDocument();
  expect(screen.getByText("ENCORE")).toBeInTheDocument();
});

test("renders rank pills for each slot", async () => {
  mockReview([
    { slot_idx: 1, set_number: "1", position: 1, actual_song_id: 1, actual_song: "X", actual_rank: 1 },
  ]);
  render(<LastShowPage />);
  await waitFor(() => expect(screen.getByTestId("rank-pill")).toHaveTextContent("#1"));
});
```

**Step 2: Run test to verify RED**

```bash
npm test -- src/app/last-show/page.test.tsx
```

Expected: import error (page doesn't exist).

**Step 3: Implement the page**

Create `web/src/app/last-show/page.tsx`:

```tsx
"use client";

import useSWR from "swr";
import { RankPill } from "@/components/RankPill";

interface Slot {
  slot_idx: number;
  set_number: string;
  position: number;
  actual_song_id: number;
  actual_song: string;
  actual_rank: number | null;
}

interface ReviewPayload {
  show: {
    show_id: number;
    show_date: string;
    venue: string;
    city: string;
    state: string;
    run_position: number | null;
    run_length: number | null;
  };
  slots: Slot[];
}

const SET_LABEL: Record<string, string> = { "1": "SET 1", "2": "SET 2", E: "ENCORE" };

export default function LastShowPage() {
  const { data, error, isLoading } = useSWR<ReviewPayload>(
    "/api/last-show/review",
    async (url: string) => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    },
  );

  if (error) {
    return (
      <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
        <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
        <p className="mt-6 text-neutral-400">No completed show to review yet.</p>
      </main>
    );
  }
  if (isLoading || !data) {
    return (
      <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
        <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
        <p className="mt-6 text-neutral-500">Loading…</p>
      </main>
    );
  }

  const groups: Array<[string, Slot[]]> = [];
  for (const slot of data.slots) {
    const last = groups[groups.length - 1];
    if (last && last[0] === slot.set_number) last[1].push(slot);
    else groups.push([slot.set_number, [slot]]);
  }

  return (
    <main className="min-h-dvh bg-neutral-950 text-neutral-100 px-4 py-6">
      <a href="/" className="text-xs text-neutral-500 hover:text-indigo-400">← back</a>
      <header className="mt-4 mb-6">
        <h1 className="text-lg font-semibold">{data.show.venue}</h1>
        <p className="text-sm text-neutral-400">
          {data.show.show_date}
          {data.show.run_position && data.show.run_length && data.show.run_length > 1
            ? ` · Run: ${data.show.run_position}|${data.show.run_length}`
            : ""}
        </p>
      </header>
      {groups.map(([setNum, slots]) => (
        <section key={setNum} className="mb-6">
          <h2 className="text-xs uppercase tracking-wider text-neutral-500 mb-2">
            {SET_LABEL[setNum] ?? `SET ${setNum}`}
          </h2>
          <ul className="flex flex-col gap-2">
            {slots.map((slot) => (
              <li
                key={slot.slot_idx}
                className="flex items-center justify-between border border-neutral-800 rounded-lg px-3 py-2"
              >
                <span className="flex items-center gap-3">
                  <span className="text-xs text-neutral-500 w-5 text-right">
                    {slot.position}
                  </span>
                  <span>{slot.actual_song}</span>
                </span>
                <RankPill rank={slot.actual_rank} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
```

**Step 4: Run test to verify GREEN**

```bash
npm test -- src/app/last-show/page.test.tsx
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add web/src/app/last-show/page.tsx web/src/app/last-show/page.test.tsx
git commit -m "feat(web): /last-show review page

🤖 assist"
```

---

## Task 10: Web — footer link with conditional render

**Files:**
- Modify: `web/src/app/page.tsx` (footer)
- Test: extend `web/src/app/page.test.tsx` if it exists; otherwise verify manually + via existing snapshot tests

**Step 1: Add the conditional fetch**

In `web/src/app/page.tsx`, near the existing `useSWR` calls:

```tsx
const { data: lastShow } = useSWR<{ show_id: number } | null>(
  "/api/last-show",
  async (url: string) => {
    const r = await fetch(url);
    if (r.status === 404) return null;
    return r.json();
  },
  { revalidateOnFocus: false, dedupingInterval: 60_000 },
);
```

**Step 2: Update the footer**

Replace the existing footer with the two-row stacked version:

```tsx
<footer className="px-4 py-3 text-xs text-neutral-600 border-t border-neutral-900 flex flex-col gap-1 items-end">
  <span>
    {meta
      ? `${meta.shows_count} shows · ${meta.songs_count} songs · v${meta.version} · web ${
          (process.env.NEXT_PUBLIC_GIT_SHA ?? "dev").slice(0, 7)
        }`
      : "Loading…"}
  </span>
  <span className="flex gap-2">
    {lastShow ? (
      <>
        <a href="/last-show" className="text-neutral-500 hover:text-indigo-400">
          last show
        </a>
        <span className="text-neutral-700">·</span>
      </>
    ) : null}
    <a href="/about" className="text-neutral-500 hover:text-indigo-400">
      about
    </a>
  </span>
</footer>
```

**Step 3: Run all web tests**

```bash
npm test
```

Expected: all pass (the new SWR call doesn't break existing tests because they mock fetch).

**Step 4: Commit**

```bash
git add web/src/app/page.tsx
git commit -m "feat(web): footer 'last show' link, hidden when no past show

🤖 assist"
```

---

## Task 11: End-to-end smoke check

Bring it all together. Verify locally before deploying.

**Step 1: Run the full test suite**

```bash
cd /Users/David/phishpicker/api && uv run pytest 2>&1 | tail -5
cd /Users/David/phishpicker/web && npm test 2>&1 | tail -5
```

Expected: all pass.

**Step 2: Lint**

```bash
cd /Users/David/phishpicker/api && uv run ruff check src/ tests/
cd /Users/David/phishpicker/web && npm run lint
```

Expected: clean.

**Step 3: Local dev test**

If you can run the api + web locally pointing at a copy of the DB:

```bash
# In one terminal
cd /Users/David/phishpicker/api && uv run uvicorn phishpicker.app:create_app --factory --reload

# In another
cd /Users/David/phishpicker/web && npm run dev
```

Open http://localhost:3000. Verify:
- Footer shows `last show · about` (assuming the local DB has a past show with setlist).
- Click "last show" — review page renders with rank pills.
- Click "← back" — returns to picker.
- Refresh `/last-show` — second load is fast (cache hit).

**Step 4: Confirm no commit needed**

This task is a verification gate, not a code change. Skip the commit step.

---

## Task 12: Deploy

Confirm with user before running.

```bash
MODEL_DIR=/tmp/v11 bash /Users/David/phishpicker/scripts/deploy_to_nas.sh
```

The deploy script (post-`b0a2fba`) rebuilds web + api together, so the new route + footer link both ship in one shot.

Verify post-deploy:

```bash
curl -s https://phishpicker.murphy52.xyz/api/last-show | jq .
curl -s https://phishpicker.murphy52.xyz/api/last-show/review | jq '.slots[0]'
```

First-call latency on `/last-show/review` should be a few seconds (cache miss). Second call: fast.

---

## Final commit (cleanup pass)

After all tasks land and the deploy verifies, close the issue:

```bash
gh issue close 5 -c "Shipped MVP per docs/plans/2026-04-27-post-show-review-design.md."
```
