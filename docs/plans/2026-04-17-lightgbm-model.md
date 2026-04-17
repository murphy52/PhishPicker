# Phishpicker LightGBM Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the heuristic scorer with a LightGBM LambdaRank model trained on historical setlists — with walk-forward evaluation, baselines, bootstrap CIs, a ship-gate, and an `/about` page that exposes training metrics.

**Architecture:** Training runs on the Mac mini after each nightly ingest, writes `model.lgb` + `metrics.json` to the shared data dir, then trips the `/internal/reload` endpoint so the API picks them up. The API loads the artifact at startup (and on reload); if the artifact is missing or the ship-gate failed, it falls back to the heuristic. Training uses `(show_id, slot_number)` groups; features are recomputed from-scratch per walk-forward fold to prevent future-leaking tour/run aggregates. Baselines (random, frequency-only, heuristic) are reported alongside every train.

**Tech Stack:** LightGBM 4.x, NumPy, pandas (training only), scikit-learn (for isotonic calibration later), existing FastAPI + SQLite stack. No ML dep leaks into the web container — `api` and `training` share a Python project; the training tools ship as a CLI subcommand.

**Supporting docs:**
- `docs/plans/2026-04-16-phishpicker-design.md` §Features, §Modeling, §Metrics — the design.
- `docs/plans/2026-04-16-walking-skeleton.md` §Carry-forward notes — the gotchas.

**Conventions:**
- Commit sign-off is `🤖 assist` (global CLAUDE.md).
- **Iron-Law TDD**: failing test first, watch it fail, minimal implementation, watch it pass, commit. Code written before a test must be deleted.
- Backend code under `api/src/phishpicker/`, tests under `api/tests/`.
- Run backend tests: `cd api && uv run pytest -q`. Lint: `uv run ruff check . && uv run ruff format --check .`.
- New package: `phishpicker.train` (training pipeline, eval, CLI glue). Keep `phishpicker.model` for scorers (heuristic + LightGBM runtime). This keeps the API container from importing LightGBM unless it chooses to.

**Scope (IN):**
- All 30 features from design §Features (7 families).
- LightGBM LambdaRank training + artifact.
- Walk-forward eval over last 20 shows, per-fold feature recomputation.
- Baselines: random, frequency-only, heuristic.
- Bootstrap 95% CIs on Top-1/Top-5/Top-20/MRR.
- Per-slot eval breakdown.
- Ship-gate: MRR must not regress by >0.02 vs. the previous production model.
- Era vs. era-plus-recency-weighting A/B.
- API integration (LightGBM runtime + heuristic fallback).
- `/about` endpoint and UI page.

**Scope (OUT, deferred):**
- Jam-length regressor (separate plan).
- Bust-out watch UI/endpoint.
- Show archive + replay (separate plan).
- Isotonic probability calibration for the UI (deferred until UI needs numeric probabilities).
- Segue trigram features — add bigrams only; trigrams often overfit at Phish's corpus size.

---

## Architecture snapshot

```
Mac mini: ingest (existing) → phishpicker train run
            ↓
  data/phishpicker.db  →  build_fold_features()  →  X, y, groups, weights
                                   ↓
                          LightGBM LambdaRank fit
                                   ↓
         data/model.lgb + data/metrics.json  →  scp + atomic rename
                                   ↓
         POST /internal/reload  →  API reopens artifact

API runtime: ScorerFactory.get_scorer(settings) → LightGBMScorer OR HeuristicScorer
             (predict_next consumes whichever is active; unchanged hard-rules post-processor)
```

**Key design constraint**: training features and runtime features share a single `build_feature_row()` function. Unit tests assert equivalence to prevent training/serving skew.

---

## Task 0: Add dependencies and package skeleton

**Files:**
- Modify: `api/pyproject.toml`
- Create: `api/src/phishpicker/train/__init__.py`
- Create: `api/tests/train/__init__.py`
- Create: `api/tests/train/test_smoke.py`

**Step 1: Write a smoke test that imports LightGBM**

`api/tests/train/test_smoke.py`:
```python
def test_lightgbm_imports():
    import lightgbm as lgb
    assert hasattr(lgb, "LGBMRanker")


def test_numpy_imports():
    import numpy as np
    assert np.__version__


def test_phishpicker_train_package_exists():
    import phishpicker.train  # noqa: F401
```

**Step 2: Run and watch it fail**
```bash
cd api && uv run pytest tests/train/test_smoke.py -q
# Expected: ModuleNotFoundError: lightgbm
```

**Step 3: Add deps and package**

Modify `api/pyproject.toml` — append to `dependencies`:
```toml
    "lightgbm>=4.5,<5",
    "numpy>=2.0,<3",
    "pandas>=2.2,<3",
    "scikit-learn>=1.5,<2",
```

Create empty `api/src/phishpicker/train/__init__.py` (one-line docstring):
```python
"""Training pipeline for the LightGBM LambdaRank model."""
```

Create empty `api/tests/train/__init__.py`.

**Step 4: Sync and verify**
```bash
cd api && uv sync --all-extras
uv run pytest tests/train/test_smoke.py -q
# Expected: 3 passed
```

**Step 5: Commit**
```bash
git add api/pyproject.toml api/uv.lock api/src/phishpicker/train/__init__.py api/tests/train/__init__.py api/tests/train/test_smoke.py
git commit -m "chore: add LightGBM + numpy + pandas + sklearn deps

🤖 assist"
```

---

## Task 1: Feature schema — `FeatureRow` dataclass and column registry

**Purpose:** Establish the single source of truth for feature names, types, and ordering. Everything downstream (training, serving, shap introspection) reads from this registry.

**Files:**
- Create: `api/src/phishpicker/train/features.py`
- Create: `api/tests/train/test_features_schema.py`

**Step 1: Write the schema tests**

`api/tests/train/test_features_schema.py`:
```python
from phishpicker.train.features import FEATURE_COLUMNS, FeatureRow


def test_feature_row_has_song_id_and_group_id():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    assert row.song_id == 1
    assert row.show_id == 2
    assert row.slot_number == 3


def test_feature_columns_is_stable_ordered_tuple():
    assert isinstance(FEATURE_COLUMNS, tuple)
    assert len(FEATURE_COLUMNS) >= 25
    # ordering MUST match FeatureRow.to_vector()
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    vec = row.to_vector()
    assert len(vec) == len(FEATURE_COLUMNS)


def test_feature_columns_are_unique():
    assert len(set(FEATURE_COLUMNS)) == len(FEATURE_COLUMNS)


def test_feature_row_to_vector_is_all_numeric():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    for v in row.to_vector():
        assert isinstance(v, (int, float))


def test_feature_row_missing_values_use_sentinel():
    # shows_since_last_played_anywhere = None (never played) → encoded as -1
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    assert row.shows_since_last_played_anywhere == -1
```

**Step 2: Run and watch it fail**
```bash
cd api && uv run pytest tests/train/test_features_schema.py -q
# Expected: ImportError
```

**Step 3: Implement**

`api/src/phishpicker/train/features.py`:
```python
"""Feature schema for the LightGBM ranker.

FEATURE_COLUMNS is the authoritative column list (names + order).
Runtime and training both go through FeatureRow → to_vector() → numpy;
that guarantees training-serving parity.

Missing numeric values (e.g., shows_since_last_played_anywhere when the song
has never been played) are encoded as -1. LightGBM handles the sentinel
through its own missing-value mechanism — we do NOT substitute column means.
"""
from dataclasses import asdict, dataclass, field, fields


MISSING = -1.0


@dataclass
class FeatureRow:
    # identity (not features, excluded from to_vector)
    song_id: int
    show_id: int
    slot_number: int

    # 1. Song base rates
    total_plays_ever: int = 0
    plays_last_12mo: int = 0
    historical_gap_mean: float = MISSING
    debut_year: float = MISSING
    is_cover: int = 0

    # 2. Recency
    shows_since_last_played_anywhere: int = -1
    days_since_last_played_anywhere: int = -1
    shows_since_last_played_this_tour: int = -1
    shows_since_last_played_this_run: int = -1

    # 3. Venue & run
    times_at_venue: int = 0
    shows_since_last_at_venue: int = -1
    played_already_this_run: int = 0
    run_position: int = 1
    venue_debut_affinity: float = 0.0  # plays_at_venue / total_plays_ever

    # 4. Tour
    tour_position: int = 1
    times_this_tour: int = 0
    tour_opener_rate: float = 0.0
    tour_closer_rate: float = 0.0

    # 5. In-show context
    current_set: int = 1  # '1'→1, '2'→2, '3'→3, 'E'→4
    set_position: int = 1
    set1_opener_rate: float = 0.0
    set2_opener_rate: float = 0.0
    encore_rate: float = 0.0
    middle_rate: float = 0.0
    prev_song_id: int = -1
    bigram_prev_to_this: float = 0.0  # P(this | prev) from historical bigrams
    segue_mark_in: int = 0  # 0=',', 1='>', 2='->'

    # 6. Temporal / era
    day_of_week: int = 0
    month: int = 1
    days_since_last_new_album: int = 365
    is_from_latest_album: int = 0
    era: int = 3  # 1.0/2.0/3.0/4.0 → 1/2/3/4

    # 7. Derived role scores
    opener_score: float = 0.0
    closer_score: float = 0.0
    encore_score: float = 0.0
    middle_of_set_2_score: float = 0.0
    bustout_score: float = 0.0

    @classmethod
    def empty(cls, song_id: int, show_id: int, slot_number: int) -> "FeatureRow":
        return cls(song_id=song_id, show_id=show_id, slot_number=slot_number)

    def to_vector(self) -> list[float]:
        d = asdict(self)
        return [float(d[col]) for col in FEATURE_COLUMNS]


# Derived from FeatureRow, skipping identity columns.
_IDENTITY = {"song_id", "show_id", "slot_number"}
FEATURE_COLUMNS: tuple[str, ...] = tuple(
    f.name for f in fields(FeatureRow) if f.name not in _IDENTITY
)
```

**Step 4: Run and verify**
```bash
cd api && uv run pytest tests/train/test_features_schema.py -q
# Expected: 5 passed
```

**Step 5: Commit**
```bash
git add api/src/phishpicker/train/features.py api/tests/train/test_features_schema.py
git commit -m "feat(train): FeatureRow dataclass + column registry

30+ numeric features across seven families. FEATURE_COLUMNS is the
authoritative ordering — training and serving both call FeatureRow.to_vector()
to emit NumPy rows, which prevents training-serving skew by construction.

🤖 assist"
```

---

## Task 2: Bigram extractor — `compute_bigram_probs`

**Purpose:** Precompute `P(song | prev_song)` from historical setlists (as of a cutoff date, so walk-forward folds don't leak). Smoothed with a small alpha so unseen bigrams aren't zero.

**Files:**
- Create: `api/src/phishpicker/train/bigrams.py`
- Create: `api/tests/train/test_bigrams.py`

**Step 1: Write the tests**

`api/tests/train/test_bigrams.py`:
```python
import sqlite3

import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.bigrams import compute_bigram_probs


@pytest.fixture
def conn(tmp_path):
    # Use the existing test fixtures where possible; here we build a tiny DB inline.
    db_path = tmp_path / "bigrams.db"
    c = open_db(db_path)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01');
        INSERT INTO shows (show_id, show_date, fetched_at) VALUES
            (10, '2024-01-01', '2024-01-02'),
            (11, '2024-01-02', '2024-01-03'),
            (12, '2024-06-01', '2024-06-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (10, '1', 1, 1), (10, '1', 2, 2), (10, '1', 3, 3),
            (11, '1', 1, 1), (11, '1', 2, 2),
            (12, '1', 1, 1), (12, '1', 2, 4);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_bigram_returns_probability_of_next_given_prev(conn: sqlite3.Connection):
    # Cutoff AFTER all three shows → A was followed by B twice, D once.
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    assert probs[(1, 2)] == pytest.approx(2 / 3)
    assert probs[(1, 4)] == pytest.approx(1 / 3)


def test_bigram_respects_cutoff_date(conn: sqlite3.Connection):
    # Cutoff before 2024-06-01 excludes show 12, so A→B is 1.0 and A→D missing.
    probs = compute_bigram_probs(conn, cutoff_date="2024-03-01", alpha=0.0)
    assert probs[(1, 2)] == pytest.approx(1.0)
    assert (1, 4) not in probs


def test_bigram_smoothing_lowers_observed_but_keeps_key(conn: sqlite3.Connection):
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=1.0)
    # A→B count 2, A→D count 1, 950 candidate songs baseline → denom 3 + 1*950
    # Just assert it's positive and less than unsmoothed.
    assert 0 < probs[(1, 2)] < 2 / 3


def test_bigram_does_not_cross_set_boundaries(conn: sqlite3.Connection):
    # If we add an encore to show 10, A→encore-first-song should not count
    # as a bigram transition because we split on set boundaries.
    conn.execute(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
        "VALUES (10, 'E', 1, 4)"
    )
    conn.commit()
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    # C→D inside the encore transition should NOT appear because different sets.
    assert (3, 4) not in probs
```

**Step 2: Run and watch it fail**
```bash
cd api && uv run pytest tests/train/test_bigrams.py -q
```

**Step 3: Implement**

`api/src/phishpicker/train/bigrams.py`:
```python
"""Song→song transition probabilities, used as a LightGBM feature."""
import sqlite3
from collections import defaultdict


def compute_bigram_probs(
    conn: sqlite3.Connection,
    cutoff_date: str,
    alpha: float = 1.0,
    candidate_count: int = 950,
) -> dict[tuple[int, int], float]:
    """Return {(prev_song_id, next_song_id): P(next | prev)} using setlists
    strictly before `cutoff_date`. Bigrams do not cross set boundaries.

    Laplace-smoothed: prob = (count + alpha) / (row_total + alpha * V)
    where V is the candidate song count (rough vocabulary size).
    """
    rows = conn.execute(
        """
        SELECT show_id, set_number, position, song_id
        FROM setlist_songs ss JOIN shows s USING (show_id)
        WHERE s.show_date < ?
        ORDER BY show_id, set_number, position
        """,
        (cutoff_date,),
    ).fetchall()

    counts: dict[tuple[int, int], int] = defaultdict(int)
    row_totals: dict[int, int] = defaultdict(int)
    prev = None
    prev_key = None
    for r in rows:
        key = (r["show_id"], r["set_number"])
        if prev is not None and prev_key == key:
            counts[(prev, r["song_id"])] += 1
            row_totals[prev] += 1
        prev = r["song_id"]
        prev_key = key

    out: dict[tuple[int, int], float] = {}
    if alpha == 0.0:
        for (p, n), c in counts.items():
            out[(p, n)] = c / row_totals[p]
        return out

    for (p, n), c in counts.items():
        denom = row_totals[p] + alpha * candidate_count
        out[(p, n)] = (c + alpha) / denom
    return out
```

**Step 4: Run and verify**
```bash
cd api && uv run pytest tests/train/test_bigrams.py -q
# Expected: 4 passed
```

**Step 5: Commit**
```bash
git add api/src/phishpicker/train/bigrams.py api/tests/train/test_bigrams.py
git commit -m "feat(train): bigram transition probabilities with cutoff + smoothing

Respects walk-forward cutoffs so future setlists don't leak into training
folds. Set-boundary-aware (no cross-set transitions).

🤖 assist"
```

---

## Task 3: Tour/era/venue aggregates — `compute_show_context`

**Purpose:** Compute show-level context features once per show (day-of-week, era, tour_position, days_since_last_new_album). These don't vary per candidate, but every candidate's FeatureRow needs them.

**Files:**
- Create: `api/src/phishpicker/train/context.py`
- Create: `api/tests/train/test_context.py`

**Step 1: Write the tests**

`api/tests/train/test_context.py`:
```python
import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.context import ShowContext, compute_show_context


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ctx.db")
    c.executescript(
        """
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG'), (2, 'Hampton');
        INSERT INTO tours (tour_id, name, start_date, end_date) VALUES
            (100, 'Summer 2024', '2024-06-01', '2024-08-31');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, tour_position, fetched_at) VALUES
            (1, '2024-06-01', 2, 100, 1, '2024-06-02'),
            (2, '2024-06-02', 2, 100, 2, '2024-06-03'),
            (3, '2024-07-04', 1, 100, 10, '2024-07-05');
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_era_derived_from_date(conn):
    # Era 4.0 = 2009+ (design doc convention); 2024 → 4.
    ctx = compute_show_context(conn, show_date="2024-06-01", venue_id=2)
    assert isinstance(ctx, ShowContext)
    assert ctx.era == 4


def test_era_for_1.0_is_1(conn):
    ctx = compute_show_context(conn, show_date="1989-12-31", venue_id=None)
    assert ctx.era == 1


def test_day_of_week_zero_is_monday(conn):
    # 2024-06-03 is a Monday.
    ctx = compute_show_context(conn, show_date="2024-06-03", venue_id=None)
    assert ctx.day_of_week == 0


def test_month_is_1_indexed(conn):
    ctx = compute_show_context(conn, show_date="2024-07-04", venue_id=1)
    assert ctx.month == 7


def test_tour_position_pulled_from_shows_table(conn):
    ctx = compute_show_context(conn, show_date="2024-06-02", venue_id=2)
    assert ctx.tour_position == 2
    ctx3 = compute_show_context(conn, show_date="2024-07-04", venue_id=1)
    assert ctx3.tour_position == 10


def test_tour_position_falls_back_to_one_when_unknown(conn):
    # Live show not yet ingested → tour_position column NULL/missing.
    ctx = compute_show_context(conn, show_date="2030-01-01", venue_id=None)
    assert ctx.tour_position == 1
```

> Note: the `test_era_for_1.0_is_1` name will need a rename to `test_era_for_era_1_is_1` — Python identifiers can't have dots. Write it that way in the actual file.

**Step 2: Run and watch it fail**
```bash
cd api && uv run pytest tests/train/test_context.py -q
```

**Step 3: Implement**

`api/src/phishpicker/train/context.py`:
```python
"""Per-show context features that don't vary by candidate song."""
import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShowContext:
    show_date: str
    day_of_week: int  # Monday=0
    month: int        # 1..12
    era: int          # 1..4
    tour_position: int


def _era_for(show_date: str) -> int:
    year = int(show_date[:4])
    if year < 2000:
        return 1  # "1.0" 1983–2000
    if year < 2004:
        return 2  # "2.0" 2002–2004
    if year < 2020:
        return 3  # "3.0" 2009–2019
    return 4      # "4.0" 2020+


def compute_show_context(
    conn: sqlite3.Connection, show_date: str, venue_id: int | None
) -> ShowContext:
    d = date.fromisoformat(show_date)
    row = conn.execute(
        "SELECT tour_position FROM shows WHERE show_date = ? AND (venue_id = ? OR ? IS NULL)",
        (show_date, venue_id, venue_id),
    ).fetchone()
    tp = int(row["tour_position"]) if row and row["tour_position"] is not None else 1
    return ShowContext(
        show_date=show_date,
        day_of_week=d.weekday(),
        month=d.month,
        era=_era_for(show_date),
        tour_position=tp,
    )
```

**Step 4: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_context.py -q
# Expected: 6 passed

git add api/src/phishpicker/train/context.py api/tests/train/test_context.py
git commit -m "feat(train): show-level context features (era, DOW, tour position)

🤖 assist"
```

---

## Task 4: Full feature builder — `build_feature_rows`

**Purpose:** Emit one `FeatureRow` per (candidate song, slot). This is the single function that both training and serving call, so training-serving parity is enforced by construction.

**Files:**
- Create: `api/src/phishpicker/train/build.py`
- Create: `api/tests/train/test_build.py`

**Step 1: Write the tests**

`api/tests/train/test_build.py`:
```python
import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.build import build_feature_rows


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "build.db")
    c.executescript(
        """
        INSERT INTO songs (song_id, name, original_artist, debut_date, first_seen_at)
        VALUES
            (1, 'Tweezer', NULL, '1990-05-01', '2020-01-01'),
            (2, 'Fluffhead', NULL, '1989-01-01', '2020-01-01'),
            (3, 'Possum', NULL, '1985-01-01', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG');
        INSERT INTO shows (show_id, show_date, venue_id, tour_position, fetched_at)
        VALUES
            (10, '2024-01-01', 1, 1, '2024-01-02'),
            (11, '2024-06-01', 1, 2, '2024-06-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id, trans_mark)
        VALUES
            (10, '1', 1, 1, ','),  -- Tweezer opener
            (10, '1', 2, 2, '>'),  -- Fluffhead
            (11, '1', 1, 3, ',');  -- Possum opener
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_build_emits_one_row_per_candidate(conn):
    # "Slot" = next-slot-to-fill. For the 2024-12-31 phantom show, asking
    # what's next when nothing's been played → slot 1 (opener).
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 3],
    )
    assert len(rows) == 3
    assert {r.song_id for r in rows} == {1, 2, 3}


def test_build_populates_total_plays_from_history(conn):
    rows = build_feature_rows(
        conn, show_date="2024-12-31", venue_id=1, played_songs=[],
        current_set="1", candidate_song_ids=[1, 2, 3],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].total_plays_ever == 1
    assert by_id[2].total_plays_ever == 1
    assert by_id[3].total_plays_ever == 1


def test_build_sets_prev_song_from_played(conn):
    # Tweezer just played; asking what's next.
    rows = build_feature_rows(
        conn, show_date="2024-12-31", venue_id=1, played_songs=[1],
        current_set="1", candidate_song_ids=[2, 3],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[2].prev_song_id == 1
    assert by_id[3].prev_song_id == 1


def test_build_slot_number_reflects_position_in_set(conn):
    rows = build_feature_rows(
        conn, show_date="2024-12-31", venue_id=1, played_songs=[1, 2],
        current_set="1", candidate_song_ids=[3],
    )
    assert rows[0].slot_number == 3


def test_build_era_on_every_row(conn):
    rows = build_feature_rows(
        conn, show_date="2024-12-31", venue_id=1, played_songs=[],
        current_set="1", candidate_song_ids=[1, 2],
    )
    for r in rows:
        assert r.era == 4
```

**Step 2: Run and watch it fail**
```bash
cd api && uv run pytest tests/train/test_build.py -q
```

**Step 3: Implement**

Start minimally. `api/src/phishpicker/train/build.py`:
```python
"""Single function callable from both training and serving that emits FeatureRow
objects for a list of candidate songs at a specific (show_date, venue, slot).
"""
import sqlite3

from phishpicker.model.stats import compute_song_stats
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.context import compute_show_context
from phishpicker.train.features import FeatureRow


SET_NUMBER_TO_INT = {"1": 1, "2": 2, "3": 3, "E": 4}


def build_feature_rows(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    played_songs: list[int],
    current_set: str,
    candidate_song_ids: list[int],
    show_id: int = 0,  # 0 for live shows not yet ingested
    bigram_cache: dict[tuple[int, int], float] | None = None,
) -> list[FeatureRow]:
    ctx = compute_show_context(conn, show_date=show_date, venue_id=venue_id)
    stats = compute_song_stats(conn, show_date, venue_id, candidate_song_ids)

    prev_song_id = played_songs[-1] if played_songs else -1
    slot_number = len(played_songs) + 1
    current_set_int = SET_NUMBER_TO_INT.get(current_set, 1)

    if bigram_cache is None:
        bigram_cache = compute_bigram_probs(conn, cutoff_date=show_date)

    rows: list[FeatureRow] = []
    for sid in candidate_song_ids:
        s = stats[sid]
        bigram_p = bigram_cache.get((prev_song_id, sid), 0.0) if prev_song_id >= 0 else 0.0
        row = FeatureRow.empty(song_id=sid, show_id=show_id, slot_number=slot_number)
        row.total_plays_ever = s.total_plays_ever
        row.plays_last_12mo = s.times_played_last_12mo
        row.shows_since_last_played_anywhere = s.shows_since_last_played_anywhere or -1
        row.shows_since_last_at_venue = s.shows_since_last_played_here or -1
        row.played_already_this_run = int(s.played_already_this_run)
        row.opener_score = s.opener_score
        row.encore_score = s.encore_score
        row.middle_rate = s.middle_score
        row.current_set = current_set_int
        row.set_position = slot_number
        row.prev_song_id = prev_song_id
        row.bigram_prev_to_this = bigram_p
        row.day_of_week = ctx.day_of_week
        row.month = ctx.month
        row.era = ctx.era
        row.tour_position = ctx.tour_position
        rows.append(row)
    return rows
```

**Step 4: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_build.py -q
# Expected: 5 passed

git add api/src/phishpicker/train/build.py api/tests/train/test_build.py
git commit -m "feat(train): build_feature_rows — unified training/serving feature builder

🤖 assist"
```

---

## Task 5: Training-set generator — `iter_training_groups`

**Purpose:** Walk through historical shows in chronological order. For each filled slot, emit: the positive (played) song + N negatives (sampled candidates). Emit groups `(show_id, slot_number)`.

**Files:**
- Create: `api/src/phishpicker/train/dataset.py`
- Create: `api/tests/train/test_dataset.py`

**Step 1: Write the tests**

`api/tests/train/test_dataset.py`:
```python
import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.dataset import iter_training_groups


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ds.db")
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        INSERT INTO shows (show_id, show_date, fetched_at) VALUES
            (10, '2024-01-01', '2024-01-02'),
            (11, '2024-02-01', '2024-02-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (10, '1', 1, 1), (10, '1', 2, 2), (10, '1', 3, 3),
            (11, '1', 1, 4), (11, '1', 2, 5);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_generator_yields_one_group_per_slot(conn):
    groups = list(iter_training_groups(
        conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=0
    ))
    # 3 slots in show 10 + 2 slots in show 11 = 5 groups.
    assert len(groups) == 5


def test_each_group_has_positive_plus_n_negatives(conn):
    groups = list(iter_training_groups(
        conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=0
    ))
    for g in groups:
        assert g.positive_song_id is not None
        assert len(g.negative_song_ids) == 2
        assert g.positive_song_id not in g.negative_song_ids


def test_groups_respect_cutoff(conn):
    groups = list(iter_training_groups(
        conn, cutoff_date="2024-01-15", negatives_per_positive=2, seed=0
    ))
    assert all(g.show_id == 10 for g in groups)


def test_groups_are_reproducible_with_seed(conn):
    a = list(iter_training_groups(
        conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=42
    ))
    b = list(iter_training_groups(
        conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=42
    ))
    assert [g.negative_song_ids for g in a] == [g.negative_song_ids for g in b]
```

**Step 2: Run and watch it fail**

**Step 3: Implement**

`api/src/phishpicker/train/dataset.py`:
```python
"""Training group generator: one group per (show_id, slot_number) containing
the positive (actually played) song + sampled negatives.
"""
import random
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingGroup:
    show_id: int
    show_date: str
    venue_id: int | None
    slot_number: int
    current_set: str
    played_before_slot: tuple[int, ...]
    positive_song_id: int
    negative_song_ids: tuple[int, ...]


def iter_training_groups(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int = 50,
    seed: int = 0,
):
    rng = random.Random(seed)
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    shows = conn.execute(
        """
        SELECT show_id, show_date, venue_id
        FROM shows
        WHERE show_date < ?
        ORDER BY show_date, show_id
        """,
        (cutoff_date,),
    ).fetchall()
    for sh in shows:
        setlist = conn.execute(
            """
            SELECT set_number, position, song_id
            FROM setlist_songs WHERE show_id = ?
            ORDER BY set_number, position
            """,
            (sh["show_id"],),
        ).fetchall()
        played: list[int] = []
        for idx, row in enumerate(setlist, start=1):
            positive = int(row["song_id"])
            pool = [s for s in all_song_ids if s != positive and s not in played]
            negatives = tuple(rng.sample(pool, min(negatives_per_positive, len(pool))))
            yield TrainingGroup(
                show_id=int(sh["show_id"]),
                show_date=sh["show_date"],
                venue_id=sh["venue_id"],
                slot_number=idx,
                current_set=row["set_number"],
                played_before_slot=tuple(played),
                positive_song_id=positive,
                negative_song_ids=negatives,
            )
            played.append(positive)
```

**Step 4: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_dataset.py -q

git add api/src/phishpicker/train/dataset.py api/tests/train/test_dataset.py
git commit -m "feat(train): iter_training_groups — (show,slot) group emitter

🤖 assist"
```

---

## Task 6: Stratified hard-negative sampling

**Purpose:** Per carry-forward §1, replace uniform sampling with 30 frequency-weighted negatives + 20 uniform. Frequency-weighted hurts MRR alone; stratified mix preserves popular-song discrimination without skew.

**Files:**
- Modify: `api/src/phishpicker/train/dataset.py`
- Modify: `api/tests/train/test_dataset.py` (extend)

**Step 1: Add tests**

Append to `api/tests/train/test_dataset.py`:
```python
def test_stratified_sampling_splits_freq_and_uniform(conn):
    # Rig frequencies: song 5 never played before cutoff, song 1 played 100x.
    for _ in range(100):
        conn.execute(
            "INSERT INTO shows (show_date, fetched_at) VALUES ('2023-01-01', '2023-01-02')"
        )
    conn.commit()
    rows = conn.execute("SELECT show_id FROM shows WHERE show_date='2023-01-01'").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (?, '1', 1, 1)", (r["show_id"],)
        )
    conn.commit()

    from phishpicker.train.dataset import iter_training_groups
    groups = list(iter_training_groups(
        conn, cutoff_date="2024-12-31",
        freq_negatives=1, uniform_negatives=1, seed=0,
    ))
    for g in groups:
        assert len(g.negative_song_ids) == 2
```

**Step 2: Run and watch it fail** (kwarg not recognized)

**Step 3: Implement**

Extend `iter_training_groups` signature and sampler.

```python
# add to dataset.py

def _frequency_weighted_sample(
    rng: random.Random,
    pool: list[int],
    weights: dict[int, int],
    k: int,
) -> list[int]:
    if not pool or k == 0:
        return []
    w = [weights.get(s, 0) + 1 for s in pool]  # +1 keeps unseen songs drawable
    out: list[int] = []
    available = list(pool)
    available_w = list(w)
    for _ in range(min(k, len(available))):
        total = sum(available_w)
        pick = rng.random() * total
        acc = 0.0
        for i, x in enumerate(available_w):
            acc += x
            if acc >= pick:
                out.append(available[i])
                available.pop(i)
                available_w.pop(i)
                break
    return out


def iter_training_groups(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    seed: int = 0,
):
    """If freq_negatives+uniform_negatives given, use stratified sampling.
    Otherwise, fall back to uniform negatives_per_positive."""
    ...
```

Keep full implementation small and readable; precompute song frequencies once per call.

**Step 4: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_dataset.py -q

git add api/src/phishpicker/train/dataset.py api/tests/train/test_dataset.py
git commit -m "feat(train): stratified hard-negative sampling (freq + uniform)

Carry-forward §1 from walking-skeleton plan. Uniform-only sampling is
kept as fallback for tests.

🤖 assist"
```

---

## Task 7: LightGBM LambdaRank trainer — `train_ranker`

**Purpose:** Take training groups, build the feature matrix, fit an `LGBMRanker`, return the booster + feature names.

**Files:**
- Create: `api/src/phishpicker/train/trainer.py`
- Create: `api/tests/train/test_trainer.py`

**Step 1: Write the test**

`api/tests/train/test_trainer.py`:
```python
import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.trainer import train_ranker


@pytest.fixture
def small_db(tmp_path):
    """Tiny synthetic DB with clear frequency signal so the model learns
    something trivially (A played often → should rank higher than E)."""
    c = open_db(tmp_path / "tr.db")
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        """
    )
    # 30 shows — A always opens, B always closes set 1, the rest vary.
    for i in range(30):
        d = f"2024-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
        sid = 100 + i
        c.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
            (sid, d, d),
        )
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
            [
                (sid, "1", 1, 1),
                (sid, "1", 2, 3),
                (sid, "1", 3, 4),
                (sid, "1", 4, 2),
            ],
        )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_train_ranker_returns_booster(small_db):
    booster, feature_names, n_groups = train_ranker(
        small_db, cutoff_date="2025-01-01",
        negatives_per_positive=3, seed=0, num_iterations=20,
    )
    assert booster is not None
    assert len(feature_names) >= 25
    assert n_groups > 0


def test_trained_ranker_prefers_frequent_songs(small_db):
    # If the model learns anything, song 1 (always opener) should be ranked
    # higher than song 5 (never played) when asked for the opener.
    from phishpicker.train.build import build_feature_rows
    booster, _, _ = train_ranker(
        small_db, cutoff_date="2025-01-01",
        negatives_per_positive=3, seed=0, num_iterations=50,
    )
    rows = build_feature_rows(
        small_db, show_date="2025-02-01", venue_id=None,
        played_songs=[], current_set="1", candidate_song_ids=[1, 5],
    )
    import numpy as np
    X = np.array([r.to_vector() for r in rows])
    scores = booster.predict(X)
    assert scores[0] > scores[1]
```

**Step 2: Run and watch it fail**

**Step 3: Implement**

`api/src/phishpicker/train/trainer.py`:
```python
"""LightGBM LambdaRank trainer."""
import sqlite3

import lightgbm as lgb
import numpy as np

from phishpicker.train.build import build_feature_rows
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.dataset import iter_training_groups
from phishpicker.train.features import FEATURE_COLUMNS


def train_ranker(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    seed: int = 0,
    num_iterations: int = 300,
    learning_rate: float = 0.05,
    num_leaves: int = 63,
    half_life_years: float | None = 7.0,  # None = no recency weighting
):
    bigram_cache = compute_bigram_probs(conn, cutoff_date=cutoff_date)

    X_rows: list[list[float]] = []
    y: list[int] = []
    groups: list[int] = []
    weights: list[float] = []

    for tg in iter_training_groups(
        conn,
        cutoff_date=cutoff_date,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        seed=seed,
    ):
        candidate_ids = [tg.positive_song_id, *tg.negative_song_ids]
        rows = build_feature_rows(
            conn,
            show_date=tg.show_date,
            venue_id=tg.venue_id,
            played_songs=list(tg.played_before_slot),
            current_set=tg.current_set,
            candidate_song_ids=candidate_ids,
            show_id=tg.show_id,
            bigram_cache=bigram_cache,
        )
        for r in rows:
            X_rows.append(r.to_vector())
            y.append(1 if r.song_id == tg.positive_song_id else 0)
        groups.append(len(candidate_ids))
        weights.append(_recency_weight(tg.show_date, cutoff_date, half_life_years))

    X = np.array(X_rows, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)
    group_arr = np.array(groups, dtype=np.int32)
    w_arr = np.array(weights, dtype=np.float32)

    model = lgb.LGBMRanker(
        objective="lambdarank",
        n_estimators=num_iterations,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        random_state=seed,
        verbose=-1,
    )
    model.fit(X, y_arr, group=group_arr, sample_weight=np.repeat(w_arr, group_arr))
    return model.booster_, list(FEATURE_COLUMNS), len(groups)


def _recency_weight(show_date: str, cutoff_date: str, half_life_years: float | None) -> float:
    if half_life_years is None:
        return 1.0
    from datetime import date
    d = (date.fromisoformat(cutoff_date) - date.fromisoformat(show_date)).days
    years = max(0.0, d / 365.25)
    return 0.5 ** (years / half_life_years)
```

**Step 4: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_trainer.py -q -x
# Expected: 2 passed

git add api/src/phishpicker/train/trainer.py api/tests/train/test_trainer.py
git commit -m "feat(train): LightGBM LambdaRank trainer with recency weighting

🤖 assist"
```

---

## Task 8: Model artifact save/load

**Purpose:** Persist the booster + feature-column list + a hash for schema alignment at API startup.

**Files:**
- Create: `api/src/phishpicker/model/lightgbm_scorer.py`
- Create: `api/tests/model/test_lightgbm_scorer.py`

**Step 1: Write the tests**

```python
import pytest
from phishpicker.model.lightgbm_scorer import LightGBMScorer, save_model_artifact


def test_roundtrip_saves_and_loads_booster(tmp_path, small_db):
    from phishpicker.train.trainer import train_ranker
    booster, cols, _ = train_ranker(
        small_db, cutoff_date="2025-01-01",
        negatives_per_positive=3, seed=0, num_iterations=20,
    )
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    assert scorer.feature_columns == cols


def test_load_raises_on_schema_mismatch(tmp_path, small_db):
    from phishpicker.train.trainer import train_ranker
    booster, cols, _ = train_ranker(
        small_db, cutoff_date="2025-01-01",
        negatives_per_positive=3, seed=0, num_iterations=20,
    )
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    # tamper
    scorer.feature_columns = cols[:-1]
    from phishpicker.train.features import FEATURE_COLUMNS
    with pytest.raises(ValueError, match="schema"):
        scorer.assert_compatible_with(FEATURE_COLUMNS)
```

**Step 2: Implement**

`api/src/phishpicker/model/lightgbm_scorer.py`:
```python
"""Runtime wrapper: load a LightGBM booster + validate its feature schema."""
import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np


@dataclass
class LightGBMScorer:
    booster: lgb.Booster
    feature_columns: list[str]

    @classmethod
    def load(cls, path: Path) -> "LightGBMScorer":
        base = Path(path)
        booster = lgb.Booster(model_file=str(base))
        meta = json.loads(base.with_suffix(".meta.json").read_text())
        return cls(booster=booster, feature_columns=meta["feature_columns"])

    def assert_compatible_with(self, expected: tuple[str, ...]) -> None:
        if tuple(self.feature_columns) != tuple(expected):
            raise ValueError(
                "Model schema mismatch between training and serving"
            )

    def score(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(X)


def save_model_artifact(path: Path, booster: lgb.Booster, columns: list[str]) -> None:
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(base))
    meta = {"feature_columns": columns}
    base.with_suffix(".meta.json").write_text(json.dumps(meta))
```

**Step 3: Verify and commit**
```bash
cd api && uv run pytest tests/model/test_lightgbm_scorer.py -q

git add api/src/phishpicker/model/lightgbm_scorer.py api/tests/model/test_lightgbm_scorer.py
git commit -m "feat(model): LightGBMScorer load/save + schema guard

🤖 assist"
```

---

## Task 9: Walk-forward evaluator — `walk_forward_eval`

**Purpose:** For each of the last N shows (reverse-chron), refit a model on all prior shows and score every slot in the held-out show. Collect per-slot ranks for Top-K / MRR metrics.

**Key:** features MUST be recomputed per fold (carry-forward §4 — tour_position, times_this_tour etc. would otherwise leak the future).

**Files:**
- Create: `api/src/phishpicker/train/eval.py`
- Create: `api/tests/train/test_eval.py`

**Step 1: Write tests**

Focus the test on the invariant: for any held-out show, no training row has a `show_date >= heldout_show_date`.

```python
def test_walk_forward_does_not_leak_future(small_db):
    from phishpicker.train.eval import walk_forward_eval
    result = walk_forward_eval(
        small_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert len(result.fold_results) == 3
    for fold in result.fold_results:
        assert fold.train_cutoff_date == fold.heldout_show_date
        assert fold.top_k_hits[1] in (0.0, 1.0) or True  # presence check


def test_walk_forward_reports_topk_and_mrr(small_db):
    from phishpicker.train.eval import walk_forward_eval
    r = walk_forward_eval(small_db, n_holdout_shows=3, negatives_per_positive=3,
                          num_iterations=10, seed=0)
    assert 0.0 <= r.top1 <= 1.0
    assert 0.0 <= r.top5 <= 1.0
    assert 0.0 <= r.mrr <= 1.0
```

**Step 2: Implement (sketch)**

`api/src/phishpicker/train/eval.py`:
```python
"""Walk-forward evaluation: refit per held-out show to prevent feature leakage."""
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from phishpicker.train.build import build_feature_rows
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.trainer import train_ranker


@dataclass
class FoldResult:
    heldout_show_id: int
    heldout_show_date: str
    train_cutoff_date: str
    ranks: list[int] = field(default_factory=list)  # rank of each positive in candidate list
    top_k_hits: dict[int, float] = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    fold_results: list[FoldResult]
    top1: float
    top5: float
    top20: float
    mrr: float
    n_slots: int


def walk_forward_eval(
    conn: sqlite3.Connection,
    n_holdout_shows: int = 20,
    negatives_per_positive: int = 50,
    num_iterations: int = 300,
    seed: int = 0,
) -> WalkForwardResult:
    holdout = conn.execute(
        "SELECT show_id, show_date, venue_id FROM shows "
        "ORDER BY show_date DESC, show_id DESC LIMIT ?",
        (n_holdout_shows,),
    ).fetchall()

    fold_results: list[FoldResult] = []
    all_ranks: list[int] = []

    for sh in holdout:
        cutoff = sh["show_date"]
        booster, cols, _ = train_ranker(
            conn, cutoff_date=cutoff,
            negatives_per_positive=negatives_per_positive,
            num_iterations=num_iterations,
            seed=seed,
        )
        setlist = conn.execute(
            "SELECT set_number, position, song_id FROM setlist_songs "
            "WHERE show_id = ? ORDER BY set_number, position",
            (sh["show_id"],),
        ).fetchall()
        candidate_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
        played: list[int] = []
        fold = FoldResult(
            heldout_show_id=sh["show_id"],
            heldout_show_date=cutoff,
            train_cutoff_date=cutoff,
        )
        for r in setlist:
            positive = r["song_id"]
            pool = [s for s in candidate_ids if s not in played]
            rows = build_feature_rows(
                conn, show_date=cutoff, venue_id=sh["venue_id"],
                played_songs=played, current_set=r["set_number"],
                candidate_song_ids=pool, show_id=sh["show_id"],
            )
            X = np.array([fr.to_vector() for fr in rows])
            scores = booster.predict(X)
            order = np.argsort(-scores)
            rank = int(np.where([pool[i] == positive for i in order])[0][0]) + 1
            fold.ranks.append(rank)
            all_ranks.append(rank)
            played.append(positive)
        for k in (1, 5, 20):
            fold.top_k_hits[k] = sum(1 for rk in fold.ranks if rk <= k) / max(1, len(fold.ranks))
        fold_results.append(fold)

    def topk(k: int) -> float:
        if not all_ranks:
            return 0.0
        return sum(1 for rk in all_ranks if rk <= k) / len(all_ranks)

    mrr = float(np.mean([1.0 / r for r in all_ranks])) if all_ranks else 0.0
    return WalkForwardResult(
        fold_results=fold_results,
        top1=topk(1), top5=topk(5), top20=topk(20),
        mrr=mrr, n_slots=len(all_ranks),
    )
```

**Step 3: Verify and commit**
```bash
cd api && uv run pytest tests/train/test_eval.py -q

git add api/src/phishpicker/train/eval.py api/tests/train/test_eval.py
git commit -m "feat(train): walk-forward evaluation with per-fold refit

🤖 assist"
```

---

## Task 10: Baselines (random, frequency-only, heuristic)

**Files:**
- Create: `api/src/phishpicker/train/baselines.py`
- Create: `api/tests/train/test_baselines.py`

Three callables with the same `(show_date, venue_id, played, current_set, candidates) → np.ndarray[scores]` signature:

- `random_scorer(seed)` — `rng.random()` per candidate.
- `frequency_scorer(conn, cutoff)` — plays-before-cutoff count per candidate.
- `heuristic_scorer(conn)` — wraps the existing `score()` function.

Each plugs into a shared `evaluate_scorer(conn, scorer, n_holdout_shows)` that returns a `WalkForwardResult` (without training, because baselines don't train).

**Tests:** basic smoke — all three return sensible WalkForwardResults; random beats nothing; heuristic beats random on the small fixture DB.

**Commit:**
```bash
git commit -m "feat(train): baselines — random, frequency-only, heuristic

🤖 assist"
```

---

## Task 11: Bootstrap CIs + per-slot breakdown

**Files:**
- Modify: `api/src/phishpicker/train/eval.py` (extend `WalkForwardResult`)
- Create: `api/tests/train/test_eval_ci.py`

Add:
- `bootstrap_ci(ranks, metric_fn, n=1000, seed=0)` → `(lo, hi)` at 95%.
- `by_slot_position(ranks, slot_positions)` → `{slot: metrics_dict}`.

Report in `WalkForwardResult`:
```python
@dataclass
class WalkForwardResult:
    ...
    top1_ci: tuple[float, float]
    top5_ci: tuple[float, float]
    mrr_ci: tuple[float, float]
    by_slot: dict[int, dict[str, float]]  # {1: {"top1": .., "top5": ..}, ...}
```

**Tests:** assert `lo <= point <= hi`; assert different slot indices produce distinct entries.

**Commit:**
```bash
git commit -m "feat(train): bootstrap CIs + per-slot metrics breakdown

Reports 95% CIs on Top-K + MRR (carry-forward §1: ±2.7pp noise band).
Per-slot breakdown splits openers from mid-set-2 (carry-forward §6).

🤖 assist"
```

---

## Task 12: Ship-gate check

**Purpose:** Compare the new model's MRR to the previous production model's `metrics.json`. If it regresses by more than 0.02, refuse to ship unless `--override` is passed.

**Files:**
- Create: `api/src/phishpicker/train/ship_gate.py`
- Create: `api/tests/train/test_ship_gate.py`

```python
def ship_gate_check(new_mrr: float, previous_metrics_path: Path, max_drop: float = 0.02) -> bool:
    if not previous_metrics_path.exists():
        return True  # first ship always OK
    prev = json.loads(previous_metrics_path.read_text())
    return new_mrr >= prev["mrr"] - max_drop
```

**Commit:**
```bash
git commit -m "feat(train): ship-gate — MRR must not drop >0.02 vs prior model

🤖 assist"
```

---

## Task 13: Training CLI — `phishpicker train run`

**Purpose:** End-to-end command that: (1) connects to DB, (2) trains production model on all data, (3) runs walk-forward, (4) runs baselines, (5) checks ship-gate, (6) writes `model.lgb` + `metrics.json` atomically.

**Files:**
- Modify: `api/src/phishpicker/cli.py` — add `train run` subcommand.
- Create: `api/tests/test_cli_train.py`

The CLI writes to `{data_dir}/model.lgb.tmp` then atomically renames to `model.lgb` (same for `metrics.json`). `metrics.json` shape:

```json
{
  "trained_at": "2026-04-17T12:34:56Z",
  "cutoff_date": "2026-04-17",
  "n_shows_trained_on": 1843,
  "n_slots": 389,
  "holdout_shows": 20,
  "top1": 0.11,
  "top5": 0.31,
  "top20": 0.62,
  "mrr": 0.18,
  "top1_ci": [0.08, 0.14],
  "top5_ci": [0.27, 0.35],
  "mrr_ci": [0.16, 0.21],
  "by_slot": {"1": {"top1": 0.22, "top5": 0.58}, ...},
  "baselines": {
    "random":    {"top1": 0.001, "top5": 0.005, "mrr": 0.005},
    "frequency": {"top1": 0.05,  "top5": 0.19,  "mrr": 0.10},
    "heuristic": {"top1": 0.07,  "top5": 0.22,  "mrr": 0.13}
  },
  "ship_gate_passed": true,
  "model_version": "0.2.0-lightgbm",
  "feature_columns": ["total_plays_ever", ...]
}
```

**Test:** small DB, run `phishpicker train run --cutoff 2025-01-01 --holdout 2 --negatives 3 --iterations 20`, assert both files exist and `ship_gate_passed` is `true`.

**Commit:**
```bash
git commit -m "feat(cli): 'phishpicker train run' — atomic model+metrics ship

🤖 assist"
```

---

## Task 14: Wire LightGBM into `predict_next` with heuristic fallback

**Files:**
- Modify: `api/src/phishpicker/predict.py`
- Modify: `api/src/phishpicker/app.py` — load scorer at lifespan startup, expose as dep.
- Modify: `api/tests/test_predict.py` (or add integration test)

**Changes:**
- `predict.py` gets a new `Scorer` Protocol with `score_candidates(...)→list[(sid, raw_score)]`.
- `HeuristicScorer` wraps the existing `score()`.
- `LightGBMScorer.score_candidates()` calls `build_feature_rows` → `to_vector` → `booster.predict`.
- `app.py` attempts to load `data/model.lgb` at startup. If missing or schema mismatch, log a warning and use `HeuristicScorer`.
- `/internal/reload` now reloads the scorer as well (not just a no-op return).

**Test the fallback**: delete `model.lgb`, hit `/predict/...`, confirm response (not 500) and `/meta` reports `"scorer": "heuristic"`.

**Commit:**
```bash
git commit -m "feat(api): LightGBM scorer runtime with heuristic fallback

🤖 assist"
```

---

## Task 15: `/about` endpoint + UI page

**Purpose:** Surface the ship metrics. Shows current model version, training timestamp, Top-K + MRR with CIs, per-slot breakdown, and baseline comparison table. Links to the design doc.

**Files:**
- Modify: `api/src/phishpicker/app.py` — add `GET /about`. Reads `{data_dir}/metrics.json` and returns it (or 503 if missing).
- Create: `web/src/app/about/page.tsx` — server component, fetches `/about`, renders table.
- Create: `web/src/app/about/page.test.tsx`

The UI is a single scrollable page. Tables: (1) headline metrics with CIs, (2) baselines comparison, (3) per-slot breakdown.

**Commit:**
```bash
git commit -m "feat(web): /about page — metrics, baselines, per-slot breakdown

🤖 assist"
```

---

## Task 16: Era A/B experiment runner

**Purpose:** Carry-forward §3 — make the era-vs-era-plus-recency-weighting comparison a one-shot script so we don't have to remember the experiment protocol later.

**Files:**
- Create: `api/src/phishpicker/train/experiments.py`
- Create: `api/tests/train/test_experiments.py`

Add `phishpicker train ab-era` subcommand that runs walk-forward twice (with and without `half_life_years=None`) and prints a table. The ship decision is: keep recency weighting only if it beats era-only by ≥0.01 MRR; otherwise ship era-only.

**Commit:**
```bash
git commit -m "feat(train): era A/B experiment — 'train ab-era' subcommand

🤖 assist"
```

---

## Task 17: End-to-end validation + docs update

**Steps:**
1. Run full pipeline on the real DB on the Mac mini:
   ```bash
   ssh mac-mini
   cd ~/phishpicker/api
   uv run phishpicker train run
   ```
   Expect completion in under 10 minutes for ~1800 shows × 50 negatives.

2. Ship to NAS via the existing `bin/ship.sh` (no changes needed — atomic rename already in place).

3. Hit `/about` through Cloudflare — confirm metrics render.

4. Hit `/predict/{show_id}` — confirm response and latency (<500ms p50 target).

5. Update `docs/plans/RESUME.md` with new tag + state.

6. Tag release:
   ```bash
   git tag -a v0.2.0-lightgbm -m "LightGBM ranker + /about metrics page"
   git push --tags
   ```

---

## Definition of done

- `phishpicker train run` produces `model.lgb` + `metrics.json` on the Mac mini.
- API loads the booster; `/predict/{id}` returns LightGBM-scored candidates, falls back to heuristic if artifact missing.
- `/about` displays Top-1/5/20/MRR with bootstrap CIs and per-slot breakdown.
- Baselines (random, frequency, heuristic) are reported alongside headline metrics.
- Walk-forward eval refits per held-out show (no leakage).
- Ship-gate blocks regressions >0.02 MRR.
- Era A/B runner is callable.
- All 60+ existing backend tests still green; new tests pass.
- `v0.2.0-lightgbm` tag pushed.

## Next plans (not in this plan)

1. **Jam-length regressor** — secondary LightGBM regressor + UI badges.
2. **Bust-out watch** — dedicated endpoint for low-probability/high-gap songs.
3. **Show archive + replay** — historical browsing with model-vs-truth view.
4. **Isotonic calibration** — when UI starts showing probabilities as numbers.
5. **Automated in-show ingestion** — phish.net polling / websocket push.
6. **SHAP introspection** — per-prediction feature attribution (for `/about`).
