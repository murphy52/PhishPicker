# Post-show Review Window Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a "last show" link in the picker footer that opens a review of the most-recent completed show, showing the actual setlist with a color-coded rank pill per slot (model's rank for the song that played).

**Architecture:** Two API endpoints — `/api/last-show` (fast metadata, drives footer link visibility) and `/api/last-show/review` (cache-or-compute, returns per-slot ranks). New `slot_predictions_cache` table keyed by `(show_id, model_sha)` so cache invalidates correctly when the deployed model changes. Slot-walking logic factored out of `nightly_smoke.py` into a shared helper so the two paths can't drift apart.

**Tech Stack:** FastAPI + sqlite (api), Next.js 16 + SWR (web), pytest (api tests), vitest (web tests). Project conventions: api commands run from `api/` dir via `uv run`; web commands run from `web/` dir via `npm`.

**Design doc:** `docs/plans/2026-04-27-post-show-review-design.md`

**Known-out-of-scope:** Setlist corrections after the cache is populated (e.g. phish.net publishes a typo fix or transition-mark correction for a past show) will not invalidate cache rows — `(show_id, model_sha)` is the key, and `model_sha` doesn't change. If a correction lands and matters, flush manually: `DELETE FROM slot_predictions_cache WHERE show_id = ?`. A `setlist_hash` column or `shows.fetched_at > computed_at` check could close this later.

**Task dependencies:**
- Task 1: none.
- Task 2: depends on Task 1 (references the helper).
- Task 3: none.
- Task 4: none.
- Task 5: none (uses only schema).
- Task 6: depends on Task 5 (resolver).
- Task 7: depends on Tasks 1, 3, 4, 5.
- Task 8: none.
- Task 9: depends on Task 8 (RankPill component).
- Task 10: depends on Task 6 (the `/last-show` endpoint).
- Task 11/12: depend on everything.

Execute linearly unless you're explicitly parallelizing — and if you do, respect the graph.

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


def test_compute_slot_ranks_orders_encore_after_numbered_sets(tmp_path):
    """Encores ('E', 'E2') must sort after numbered sets ('1', '2', '3'),
    matching nightly_smoke._slot_sort_key. Lex order would mostly work
    ('1' < 'E') but 'E2' would lex-sort before any numbered set.
    """
    c = open_db(tmp_path / "ord.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'V');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at)
        VALUES (200, '2026-04-25', 10, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (200, '1', 1, 1),
            (200, '3', 1, 3),
            (200, 'E', 1, 4),
            (200, 'E2', 1, 5);
        """
    )
    c.commit()
    scorer = FakeScorer(name="t", top_order=[1, 3, 4, 5])
    rows = compute_slot_ranks(c, show_id=200, scorer=scorer)
    c.close()
    assert [r.set_number for r in rows] == ["1", "3", "E", "E2"]


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


# Mirrors nightly_smoke._slot_sort_key. Module-level so other callers
# (e.g. /last-show/review's cache-hit path) can re-derive slot ordering.
_SET_ORDER = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}


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

    raw = conn.execute(
        "SELECT set_number, position, song_id, trans_mark "
        "FROM setlist_songs WHERE show_id = ?",
        (show_id,),
    ).fetchall()
    if not raw:
        return []

    # Match nightly_smoke._slot_sort_key: encores ('E', 'E2', 'E3') sort
    # after numbered sets. Pure lex order ('1' < 'E') is wrong for 'E2'.
    setlist = sorted(
        raw,
        key=lambda r: (_SET_ORDER.get(str(r["set_number"]).upper(), 99), int(r["position"])),
    )

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

## Task 2: Cross-link nightly_smoke to the helper

**Decision:** do not refactor `nightly_smoke.py` to use `compute_slot_ranks`. The helper covers walk-and-rank; nightly-smoke also needs per-slot top-K enrichment, which the cache and review endpoint don't need. Forcing the helper to grow a `top_k=True` option in v1 would inflate scope. Instead, leave both in place and cross-link them so future-us doesn't accidentally let them drift.

**Files:**
- Modify: `api/src/phishpicker/nightly_smoke.py`

**Step 1: Add the TODO comment**

Open `api/src/phishpicker/nightly_smoke.py`, find the per-slot loop (search for `slots_into_current_set` — currently around lines 145-200), and add immediately before the loop:

```python
# TODO(slot-ranks-dedup): this walk duplicates compute_slot_ranks in
# phishpicker.slot_ranks. Keep them in sync — both implement set ordering
# via _slot_sort_key/_SET_ORDER and identical scorer kwargs. Consolidate
# when nightly-smoke no longer needs top-K enrichment, or when the helper
# grows a top_k=True option. See docs/plans/2026-04-27-post-show-review-design.md.
```

**Step 2: Verify nightly_smoke tests still pass**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/test_nightly_smoke.py -xvs
```

Expected: all pass (no behavior change).

**Step 3: Commit**

```bash
git add api/src/phishpicker/nightly_smoke.py
git commit -m "docs(api): cross-link nightly_smoke walk to shared slot_ranks helper

🤖 assist"
```

---

## Task 3: Add `slot_predictions_cache` table to schema

`apply_schema` reads the canonical schema from `db/schema.sql` and `executescript`s it. Add the new table there, not as a Python-injected `executescript` block.

**Files:**
- Modify: `api/src/phishpicker/db/schema.sql`
- Test: `api/tests/db/test_schema_slot_cache.py`

**Step 1: Write the failing test**

Create `api/tests/db/test_schema_slot_cache.py`:

```python
import sqlite3

import pytest

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


def test_slot_predictions_cache_unique_per_show_model_slot(tmp_path):
    """Two inserts with the same (show_id, model_sha, slot_idx) must collide."""
    c = open_db(tmp_path / "pk.db")
    apply_schema(c)
    c.execute(
        "INSERT INTO slot_predictions_cache "
        "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
        "VALUES (1, 'sha', 1, 100, 7, '2026-04-26T00:00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO slot_predictions_cache "
            "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
            "VALUES (1, 'sha', 1, 100, 99, '2026-04-26T00:00:00')"
        )
```

**Step 2: Run test to verify RED**

```bash
cd /Users/David/phishpicker/api
uv run pytest tests/db/test_schema_slot_cache.py -xvs
```

Expected: errors complaining the table doesn't exist.

**Step 3: Add the table to schema.sql**

Append to `api/src/phishpicker/db/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS slot_predictions_cache (
    show_id INTEGER NOT NULL REFERENCES shows(show_id),
    model_sha TEXT NOT NULL,
    slot_idx INTEGER NOT NULL,
    actual_song_id INTEGER NOT NULL REFERENCES songs(song_id),
    actual_rank INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (show_id, model_sha, slot_idx)
);
CREATE INDEX IF NOT EXISTS idx_slot_cache_show_model
    ON slot_predictions_cache(show_id, model_sha);
```

**Step 4: Run test to verify GREEN**

```bash
uv run pytest tests/db/test_schema_slot_cache.py -xvs
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add api/src/phishpicker/db/schema.sql api/tests/db/test_schema_slot_cache.py
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


def test_review_cache_hit_serves_stored_rank(client, tmp_path):
    """First call populates the cache. Mutate the cache row directly,
    then call again — if the response reflects the mutation, the cache
    was served (no recompute). If it reflects the model's true rank,
    the cache was bypassed."""
    from phishpicker.db.connection import open_db

    # Prime the cache.
    r1 = client.get("/last-show/review")
    assert r1.status_code == 200
    assert len(r1.json()["slots"]) >= 1

    # Tamper: set every cached actual_rank to a sentinel.
    with open_db(tmp_path / "phishpicker.db") as db:
        db.execute("UPDATE slot_predictions_cache SET actual_rank = 999")
        db.commit()

    # Second call must return the tampered value — proves cache served.
    r2 = client.get("/last-show/review")
    assert r2.status_code == 200
    assert all(s["actual_rank"] == 999 for s in r2.json()["slots"])


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

Note: `open_db` may return a read-only connection by default — check the signature in `db/connection.py`. If so, use `open_db(path, read_only=False)` for the tamper UPDATE, or open via raw `sqlite3.connect` for the test only.

**Step 2: Add the endpoint**

Two paths share the response shape (`slot_idx`, `actual_rank`) — on cache miss we use the just-computed `ranks` directly, on cache hit we use the loaded rows. No re-read across connections, no window-function gymnastics.

In `api/src/phishpicker/app.py`:

```python
@app.get("/last-show/review")
def last_show_review(
    request: Request,
    read: sqlite3.Connection = Depends(get_read),  # noqa: B008
):
    from contextlib import closing
    from datetime import UTC, datetime
    from phishpicker.db.connection import open_db
    from phishpicker.last_show import resolve_last_show_id
    from phishpicker.slot_ranks import compute_slot_ranks

    show_id = resolve_last_show_id(read)
    if show_id is None:
        raise HTTPException(404, "no completed shows")

    scorer = request.app.state.scorer
    model_sha = scorer.sha

    # Cache check: count must match setlist length AND map by slot_idx.
    cached = {
        r["slot_idx"]: (int(r["actual_song_id"]), r["actual_rank"])
        for r in read.execute(
            "SELECT slot_idx, actual_song_id, actual_rank "
            "FROM slot_predictions_cache WHERE show_id = ? AND model_sha = ?",
            (show_id, model_sha),
        ).fetchall()
    }
    setlist_count = read.execute(
        "SELECT COUNT(*) FROM setlist_songs WHERE show_id = ?",
        (show_id,),
    ).fetchone()[0]

    if len(cached) == setlist_count:
        # Cache hit. Reconstruct slot_idx → (set_number, position, song name)
        # by walking setlist_songs in the same canonical order the helper uses.
        from phishpicker.slot_ranks import _SET_ORDER  # promoted to module scope in Task 1
        raw = read.execute(
            "SELECT set_number, position, song_id FROM setlist_songs WHERE show_id = ?",
            (show_id,),
        ).fetchall()
        setlist = sorted(
            raw,
            key=lambda r: (
                _SET_ORDER.get(str(r["set_number"]).upper(), 99),
                int(r["position"]),
            ),
        )
        song_names = {
            r["song_id"]: r["name"]
            for r in read.execute("SELECT song_id, name FROM songs")
        }
        slots_out = []
        for idx, s in enumerate(setlist, start=1):
            rank_entry = cached.get(idx)
            actual_rank = rank_entry[1] if rank_entry else None
            slots_out.append({
                "slot_idx": idx,
                "set_number": s["set_number"],
                "position": int(s["position"]),
                "actual_song_id": int(s["song_id"]),
                "actual_song": song_names.get(s["song_id"], f"#{s['song_id']}"),
                "actual_rank": actual_rank,
            })
    else:
        # Cache miss — compute, write, and use in-memory results directly.
        ranks = compute_slot_ranks(read, show_id=show_id, scorer=scorer)
        now = datetime.now(UTC).isoformat()
        with closing(open_db(request.app.state.settings.db_path, read_only=False)) as write:
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
        song_names = {
            r["song_id"]: r["name"]
            for r in read.execute("SELECT song_id, name FROM songs")
        }
        slots_out = [
            {
                "slot_idx": r.slot_idx,
                "set_number": r.set_number,
                "position": r.position,
                "actual_song_id": r.actual_song_id,
                "actual_song": song_names.get(r.actual_song_id, f"#{r.actual_song_id}"),
                "actual_rank": r.actual_rank,
            }
            for r in ranks
        ]

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
        "slots": slots_out,
    }
```

**Helper export needed:** the cache-hit path imports `_SET_ORDER` from `phishpicker.slot_ranks` to rebuild slot ordering. When you write Task 1's helper, define `_SET_ORDER` at module scope (not as a local inside `compute_slot_ranks`) so this import works.

`open_db(path, read_only=False)` is the actual signature in `db/connection.py` — it returns a thread-safe connection with `busy_timeout=5000`, `foreign_keys=ON`, and `row_factory=sqlite3.Row` set.

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
import { SWRConfig } from "swr";
import LastShowPage from "./page";

afterEach(() => vi.restoreAllMocks());

// SWR caches by key globally — without a fresh provider per render, test 2
// gets test 1's response from cache and never calls the new mocked fetch.
function renderIsolated() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <LastShowPage />
    </SWRConfig>,
  );
}

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
  renderIsolated();
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
  renderIsolated();
  await waitFor(() => expect(screen.getByTestId("rank-pill")).toHaveTextContent("#1"));
});

test("shows empty state when API returns 404", async () => {
  global.fetch = vi.fn(async () => ({
    ok: false,
    status: 404,
    json: async () => null,
  })) as unknown as typeof fetch;
  renderIsolated();
  await waitFor(() =>
    expect(screen.getByText(/no completed show/i)).toBeInTheDocument(),
  );
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
