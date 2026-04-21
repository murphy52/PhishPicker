# Prediction-vs-Actual Retrospective Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a retrospective harness that diffs saved ahead-of-show
previews against the real setlist (plus nightly-smoke JSONL), emitting a
stdout summary and a markdown retro for each Sphere night 4-9.

**Architecture:** Library-first. All logic lives in
`api/src/phishpicker/retro.py` as pure functions over dataclasses; the
CLI script `scripts/compare_prediction_to_actual.py` is thin glue.
Preview scripts (`preview_night4.py`, `preview_residency.py`) gain a
small save step so ahead-of-show predictions are locked in JSON before
Night 4 exists.

**Tech Stack:** Python 3.12, pytest, sqlite3, dataclasses, stdlib json —
no new dependencies. Follows the existing `phishpicker` repo conventions
(cf. `api/src/phishpicker/nightly_smoke.py`, `api/src/phishpicker/replay.py`).

**Design doc:** `docs/plans/2026-04-21-prediction-vs-actual-retro-design.md`

**Testing commands:**
- Run one test: `cd api && ~/.local/bin/uv run pytest tests/test_retro.py::<test_name> -v`
- Run whole suite: `cd api && ~/.local/bin/uv run pytest -q`

---

## Task 1: Scaffold `retro.py` dataclasses + empty test file

**Files:**
- Create: `api/src/phishpicker/retro.py`
- Create: `api/tests/test_retro.py`

**Step 1: Create the module with dataclasses only**

```python
# api/src/phishpicker/retro.py
"""Retrospective harness — diff ahead-of-show previews against actual
setlists + nightly-smoke JSONL. Pure-python library; the CLI in
scripts/compare_prediction_to_actual.py is thin glue."""

from dataclasses import dataclass, field


@dataclass
class PreviewPick:
    slot_idx: int
    set: str           # "SET 1" | "SET 2" | "ENCORE"
    song_id: int
    name: str


@dataclass
class PreviewDoc:
    show_date: str
    venue_id: int | None
    generated_at: str
    model_path: str
    picks: list[PreviewPick]


@dataclass
class ActualSlot:
    slot_idx: int      # 1-indexed across the show
    set_number: str    # "1", "2", "E" as in DB
    position: int      # position within the set
    song_id: int
    name: str


@dataclass
class SmokeSlotRank:
    slot: int
    actual_song: str
    actual_rank: int | None


@dataclass
class SmokeRecord:
    date: str
    show_id: int
    venue: str
    slots: list[SmokeSlotRank]


@dataclass
class SlotMatch:
    slot_idx: int
    predicted: str | None
    actual: str | None
    exact_match: bool


@dataclass
class Retro:
    show_date: str
    venue: str
    preview_picks: list[PreviewPick]
    actual_slots: list[ActualSlot]
    smoke: SmokeRecord | None
    # Derived analyses — populated by compare():
    set_overlap_songs: list[str] = field(default_factory=list)
    preview_only_songs: list[str] = field(default_factory=list)
    actual_only_songs: list[str] = field(default_factory=list)
    slot_matches: list[SlotMatch] = field(default_factory=list)
    actual_ranks_in_preview: dict[str, int | None] = field(default_factory=dict)
```

**Step 2: Create empty test file**

```python
# api/tests/test_retro.py
"""Tests for the retrospective harness."""

from phishpicker.retro import (
    ActualSlot,
    PreviewDoc,
    PreviewPick,
    Retro,
    SlotMatch,
    SmokeRecord,
    SmokeSlotRank,
)


def test_module_imports() -> None:
    # Smoke test: dataclasses are constructible.
    PreviewPick(slot_idx=1, set="SET 1", song_id=1, name="x")
    PreviewDoc(show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p", picks=[])
    ActualSlot(slot_idx=1, set_number="1", position=1, song_id=1, name="x")
    SmokeSlotRank(slot=1, actual_song="x", actual_rank=5)
    SmokeRecord(date="2026-04-23", show_id=1, venue="v", slots=[])
    SlotMatch(slot_idx=1, predicted="x", actual="x", exact_match=True)
    Retro(show_date="2026-04-23", venue="v", preview_picks=[], actual_slots=[], smoke=None)
```

**Step 3: Run tests**

```
cd api && ~/.local/bin/uv run pytest tests/test_retro.py -q
```
Expected: 1 passed.

**Step 4: Commit**

```bash
git add api/src/phishpicker/retro.py api/tests/test_retro.py
git commit -m "feat(retro): scaffold dataclasses for prediction-vs-actual retro"
```

---

## Task 2: Implement `load_preview`

**Files:**
- Modify: `api/src/phishpicker/retro.py`
- Modify: `api/tests/test_retro.py`

**Step 1: Write failing test**

Add to `test_retro.py`:

```python
import json
from pathlib import Path
import pytest
from phishpicker.retro import load_preview


def test_load_preview_parses_saved_json(tmp_path: Path) -> None:
    payload = {
        "show_date": "2026-04-23",
        "venue_id": 1597,
        "generated_at": "2026-04-21T15:30:00Z",
        "model_path": "data/model.lgb",
        "pass": "RAW",
        "picks": [
            {"slot_idx": 1, "set": "SET 1", "song_id": 123, "name": "Buried Alive"},
            {"slot_idx": 2, "set": "SET 1", "song_id": 456, "name": "Moma Dance"},
        ],
    }
    p = tmp_path / "preview.json"
    p.write_text(json.dumps(payload))

    doc = load_preview(p)
    assert doc.show_date == "2026-04-23"
    assert doc.venue_id == 1597
    assert len(doc.picks) == 2
    assert doc.picks[0].name == "Buried Alive"
    assert doc.picks[1].song_id == 456


def test_load_preview_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_preview(tmp_path / "nope.json")
```

**Step 2: Run to confirm failure**

```
cd api && ~/.local/bin/uv run pytest tests/test_retro.py::test_load_preview_parses_saved_json -v
```
Expected: ImportError on `load_preview`.

**Step 3: Implement**

Add to `retro.py`:

```python
import json
from pathlib import Path


def load_preview(path: Path) -> PreviewDoc:
    raw = json.loads(path.read_text())
    picks = [
        PreviewPick(
            slot_idx=p["slot_idx"],
            set=p["set"],
            song_id=p["song_id"],
            name=p["name"],
        )
        for p in raw["picks"]
    ]
    return PreviewDoc(
        show_date=raw["show_date"],
        venue_id=raw.get("venue_id"),
        generated_at=raw["generated_at"],
        model_path=raw["model_path"],
        picks=picks,
    )
```

**Step 4: Run tests — expect pass**

```
cd api && ~/.local/bin/uv run pytest tests/test_retro.py -q
```

**Step 5: Commit**

```bash
git add api/src/phishpicker/retro.py api/tests/test_retro.py
git commit -m "feat(retro): load_preview — parse saved preview JSON"
```

---

## Task 3: Implement `load_actual_setlist`

**Files:** modify `retro.py` + `test_retro.py`.

**Step 1: Write failing test**

Existing tests for the codebase use in-memory sqlite with the production
schema. Follow that idiom.

```python
import sqlite3


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE shows (show_id INTEGER PRIMARY KEY, show_date TEXT, venue_id INTEGER);
        CREATE TABLE venues (venue_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE songs (song_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE setlist_songs (
            show_id INTEGER, set_number TEXT, position INTEGER,
            song_id INTEGER, trans_mark TEXT
        );
    """)
    return conn


def test_load_actual_setlist_returns_slots_in_order() -> None:
    from phishpicker.retro import load_actual_setlist
    conn = _make_db()
    conn.executescript("""
        INSERT INTO venues VALUES (1597, 'Sphere');
        INSERT INTO shows VALUES (9001, '2026-04-23', 1597);
        INSERT INTO songs VALUES (1, 'Buried Alive'), (2, 'Moma Dance'), (3, 'Tweezer Reprise');
        INSERT INTO setlist_songs VALUES
            (9001, '1', 1, 1, ','),
            (9001, '1', 2, 2, ','),
            (9001, 'E', 1, 3, ',');
    """)

    slots = load_actual_setlist(conn, "2026-04-23")
    assert len(slots) == 3
    assert slots[0].slot_idx == 1
    assert slots[0].name == "Buried Alive"
    assert slots[0].set_number == "1"
    assert slots[2].set_number == "E"
    # encore sorts after set 2 in slot order
    assert slots[2].slot_idx == 3


def test_load_actual_setlist_missing_show_returns_empty() -> None:
    from phishpicker.retro import load_actual_setlist
    conn = _make_db()
    assert load_actual_setlist(conn, "1999-01-01") == []
```

**Step 2: Confirm failure** (`load_actual_setlist` not defined).

**Step 3: Implement**

```python
_SET_ORDER = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}


def load_actual_setlist(conn, show_date: str) -> list[ActualSlot]:
    rows = conn.execute(
        """
        SELECT ss.set_number, ss.position, ss.song_id, s.name
        FROM shows sh
        JOIN setlist_songs ss USING (show_id)
        JOIN songs s USING (song_id)
        WHERE sh.show_date = ?
        """,
        (show_date,),
    ).fetchall()
    # Sort by (set-order, position). Use .get(..., 99) so unknown labels sort last.
    rows = sorted(rows, key=lambda r: (_SET_ORDER.get(str(r["set_number"]).upper(), 99), r["position"]))
    return [
        ActualSlot(slot_idx=i + 1, set_number=r["set_number"], position=r["position"],
                   song_id=r["song_id"], name=r["name"])
        for i, r in enumerate(rows)
    ]
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): load_actual_setlist — read + order slots from DB"
```

---

## Task 4: Implement `load_smoke_record`

**Files:** modify `retro.py` + `test_retro.py`.

**Step 1: Write failing test**

```python
def test_load_smoke_record_finds_matching_date(tmp_path: Path) -> None:
    from phishpicker.retro import load_smoke_record
    jsonl = tmp_path / "smoke.jsonl"
    rec1 = {"date": "2026-04-16", "show_id": 1, "venue": "Sphere", "slots": [
        {"slot": 1, "actual_song": "Sample in a Jar", "actual_rank": 7}
    ]}
    rec2 = {"date": "2026-04-23", "show_id": 2, "venue": "Sphere", "slots": [
        {"slot": 1, "actual_song": "Buried Alive", "actual_rank": 1},
        {"slot": 2, "actual_song": "Moma Dance", "actual_rank": 4},
    ]}
    jsonl.write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n")

    rec = load_smoke_record(jsonl, "2026-04-23")
    assert rec is not None
    assert rec.show_id == 2
    assert len(rec.slots) == 2
    assert rec.slots[0].actual_rank == 1


def test_load_smoke_record_missing_date_returns_none(tmp_path: Path) -> None:
    from phishpicker.retro import load_smoke_record
    jsonl = tmp_path / "smoke.jsonl"
    jsonl.write_text(json.dumps({"date": "2025-01-01", "show_id": 1, "venue": "x", "slots": []}) + "\n")
    assert load_smoke_record(jsonl, "2026-04-23") is None


def test_load_smoke_record_missing_file_returns_none(tmp_path: Path) -> None:
    from phishpicker.retro import load_smoke_record
    assert load_smoke_record(tmp_path / "nope.jsonl", "2026-04-23") is None
```

**Step 2: Confirm failure.**

**Step 3: Implement**

```python
def load_smoke_record(jsonl_path: Path, date: str) -> SmokeRecord | None:
    if not jsonl_path.exists():
        return None
    for line in jsonl_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("date") == date:
            slots = [
                SmokeSlotRank(
                    slot=s["slot"],
                    actual_song=s["actual_song"],
                    actual_rank=s.get("actual_rank"),
                )
                for s in rec.get("slots", [])
            ]
            return SmokeRecord(
                date=rec["date"],
                show_id=rec["show_id"],
                venue=rec.get("venue", ""),
                slots=slots,
            )
    return None
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): load_smoke_record — find record by date in JSONL"
```

---

## Task 5: Implement `compare` — set-level overlap

**Files:** modify `retro.py` + `test_retro.py`.

**Step 1: Write failing test**

```python
def test_compare_set_level_overlap() -> None:
    from phishpicker.retro import compare
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "Buried Alive"),
            PreviewPick(2, "SET 1", 2, "Moma Dance"),
            PreviewPick(3, "SET 2", 3, "Oblivion"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 1, "Buried Alive"),
        ActualSlot(2, "1", 2, 99, "Sample in a Jar"),  # not predicted
        ActualSlot(3, "2", 1, 3, "Oblivion"),
    ]
    r = compare(preview, actual, smoke=None)
    assert set(r.set_overlap_songs) == {"Buried Alive", "Oblivion"}
    assert r.preview_only_songs == ["Moma Dance"]
    assert r.actual_only_songs == ["Sample in a Jar"]
```

**Step 2: Confirm failure.**

**Step 3: Implement initial `compare`**

```python
def compare(
    preview: PreviewDoc,
    actual: list[ActualSlot],
    smoke: SmokeRecord | None,
    venue: str = "",
) -> Retro:
    preview_names = [p.name for p in preview.picks]
    actual_names = [a.name for a in actual]
    preview_set = set(preview_names)
    actual_set = set(actual_names)
    overlap = preview_set & actual_set
    # Preserve preview order for overlap; deterministic.
    overlap_ordered = [n for n in preview_names if n in overlap and
                       preview_names.index(n) == preview_names.index(n)]
    # dedupe while preserving order
    seen: set[str] = set()
    overlap_ordered = [n for n in preview_names if n in overlap and not (n in seen or seen.add(n))]
    preview_only = [n for n in preview_names if n not in actual_set]
    actual_only = [n for n in actual_names if n not in preview_set]

    return Retro(
        show_date=preview.show_date,
        venue=venue,
        preview_picks=list(preview.picks),
        actual_slots=list(actual),
        smoke=smoke,
        set_overlap_songs=overlap_ordered,
        preview_only_songs=preview_only,
        actual_only_songs=actual_only,
    )
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): compare — set-level overlap analysis"
```

---

## Task 6: Extend `compare` — slot-level match

**Step 1: Add failing test**

```python
def test_compare_slot_level_match() -> None:
    from phishpicker.retro import compare
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "A"),
            PreviewPick(2, "SET 1", 2, "B"),
            PreviewPick(3, "SET 1", 3, "C"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 1, "A"),  # exact match
        ActualSlot(2, "1", 2, 99, "X"), # miss
        ActualSlot(3, "1", 3, 3, "C"),  # exact match
    ]
    r = compare(preview, actual, smoke=None)
    assert len(r.slot_matches) == 3
    assert r.slot_matches[0].exact_match
    assert not r.slot_matches[1].exact_match
    assert r.slot_matches[2].exact_match
    assert r.slot_matches[1].predicted == "B"
    assert r.slot_matches[1].actual == "X"


def test_compare_slot_mismatch_in_length() -> None:
    from phishpicker.retro import compare
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p",
        picks=[PreviewPick(1, "SET 1", 1, "A"), PreviewPick(2, "SET 1", 2, "B")],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A")]  # only one slot actually played
    r = compare(preview, actual, smoke=None)
    # 2 rows emitted — slot 2's actual is None
    assert len(r.slot_matches) == 2
    assert r.slot_matches[1].predicted == "B"
    assert r.slot_matches[1].actual is None
    assert not r.slot_matches[1].exact_match
```

**Step 2: Confirm failure.**

**Step 3: Extend `compare`**

Before the `return Retro(...)` line, compute slot matches:

```python
    slot_matches: list[SlotMatch] = []
    n = max(len(preview.picks), len(actual))
    for i in range(n):
        pred = preview.picks[i].name if i < len(preview.picks) else None
        act = actual[i].name if i < len(actual) else None
        slot_matches.append(
            SlotMatch(
                slot_idx=i + 1,
                predicted=pred,
                actual=act,
                exact_match=(pred is not None and pred == act),
            )
        )
```

And pass `slot_matches=slot_matches` to the `Retro(...)` constructor.

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): compare — slot-level match + length-mismatch tolerance"
```

---

## Task 7: Extend `compare` — rank-of-actual-in-preview

**Step 1: Add failing test**

```python
def test_compare_rank_of_actual_in_preview() -> None:
    from phishpicker.retro import compare
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "A"),
            PreviewPick(2, "SET 1", 2, "B"),
            PreviewPick(3, "SET 1", 3, "C"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 3, "C"),  # was predicted at slot 3
        ActualSlot(2, "1", 2, 99, "X"), # not in preview at all
    ]
    r = compare(preview, actual, smoke=None)
    assert r.actual_ranks_in_preview["C"] == 3
    assert r.actual_ranks_in_preview["X"] is None
```

**Step 2: Confirm failure.**

**Step 3: Extend `compare`**

```python
    actual_ranks_in_preview: dict[str, int | None] = {}
    preview_name_to_rank = {p.name: p.slot_idx for p in preview.picks}
    for a in actual:
        actual_ranks_in_preview[a.name] = preview_name_to_rank.get(a.name)
```

Pass `actual_ranks_in_preview=actual_ranks_in_preview` in `Retro(...)`.

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): compare — rank of each actual song in preview"
```

---

## Task 8: Add smoke-rank summary helpers

**Step 1: Add failing test**

```python
def test_smoke_rank_summary() -> None:
    from phishpicker.retro import smoke_rank_summary
    smoke = SmokeRecord(
        date="2026-04-23", show_id=1, venue="Sphere",
        slots=[
            SmokeSlotRank(slot=1, actual_song="A", actual_rank=1),
            SmokeSlotRank(slot=2, actual_song="B", actual_rank=4),
            SmokeSlotRank(slot=3, actual_song="C", actual_rank=7),
            SmokeSlotRank(slot=4, actual_song="D", actual_rank=None),  # not rankable
        ],
    )
    s = smoke_rank_summary(smoke)
    assert s["n_ranked"] == 3
    assert s["top1"] == 1
    assert s["top5"] == 2
    assert s["top10"] == 3
    assert s["median"] == 4


def test_smoke_rank_summary_none_input() -> None:
    from phishpicker.retro import smoke_rank_summary
    assert smoke_rank_summary(None) is None
```

**Step 2: Confirm failure.**

**Step 3: Implement**

```python
def smoke_rank_summary(smoke: SmokeRecord | None) -> dict | None:
    if smoke is None:
        return None
    ranks = [s.actual_rank for s in smoke.slots if s.actual_rank is not None]
    if not ranks:
        return {"n_ranked": 0, "top1": 0, "top5": 0, "top10": 0, "median": None}
    ranks_sorted = sorted(ranks)
    median = ranks_sorted[len(ranks_sorted) // 2]
    return {
        "n_ranked": len(ranks),
        "top1": sum(1 for r in ranks if r == 1),
        "top5": sum(1 for r in ranks if r <= 5),
        "top10": sum(1 for r in ranks if r <= 10),
        "median": median,
    }
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): smoke_rank_summary — aggregate stats from JSONL record"
```

---

## Task 9: Implement `render_stdout_summary`

**Step 1: Add failing test**

```python
def test_render_stdout_summary_basic() -> None:
    from phishpicker.retro import render_stdout_summary
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p",
        picks=[PreviewPick(1, "SET 1", 1, "A"), PreviewPick(2, "SET 1", 2, "B")],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A"), ActualSlot(2, "1", 2, 99, "C")]
    smoke = SmokeRecord(
        date="2026-04-23", show_id=1, venue="Sphere",
        slots=[SmokeSlotRank(1, "A", 1), SmokeSlotRank(2, "C", 12)],
    )
    from phishpicker.retro import compare
    r = compare(preview, actual, smoke, venue="Sphere")
    out = render_stdout_summary(r)
    assert "2026-04-23" in out
    assert "Sphere" in out
    # set overlap reported
    assert "1 song" in out or "1/" in out or "overlap" in out.lower()
    # smoke top-1 reported
    assert "1/2" in out or "Top-1" in out


def test_render_stdout_summary_without_smoke() -> None:
    from phishpicker.retro import render_stdout_summary, compare
    preview = PreviewDoc(show_date="2026-04-23", venue_id=1, generated_at="t",
                        model_path="p", picks=[PreviewPick(1, "SET 1", 1, "A")])
    actual = [ActualSlot(1, "1", 1, 1, "A")]
    r = compare(preview, actual, smoke=None, venue="Sphere")
    out = render_stdout_summary(r)
    assert out  # does not crash
    assert "smoke" in out.lower() or "nightly" in out.lower()  # notes smoke absent
```

**Step 2: Confirm failure.**

**Step 3: Implement**

```python
def render_stdout_summary(retro: Retro) -> str:
    lines: list[str] = []
    lines.append(f"=== Retro — {retro.show_date} {retro.venue} ===")
    lines.append(f"Preview picks: {len(retro.preview_picks)}  Actual slots: {len(retro.actual_slots)}")
    lines.append(
        f"Set-level overlap: {len(retro.set_overlap_songs)} songs "
        f"({len(retro.set_overlap_songs)}/{len(retro.preview_picks)} of preview)"
    )
    exact = sum(1 for m in retro.slot_matches if m.exact_match)
    lines.append(f"Slot-level exact matches: {exact}/{len(retro.slot_matches)}")

    smoke_summary = smoke_rank_summary(retro.smoke)
    if smoke_summary is None:
        lines.append("Nightly-smoke: (no record for this date)")
    else:
        n = smoke_summary["n_ranked"]
        lines.append(
            f"Nightly-smoke: Top-1 {smoke_summary['top1']}/{n} · "
            f"Top-5 {smoke_summary['top5']}/{n} · "
            f"Top-10 {smoke_summary['top10']}/{n} · "
            f"median rank {smoke_summary['median']}"
        )
    return "\n".join(lines)
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): render_stdout_summary — headline retro lines"
```

---

## Task 10: Implement `render_markdown`

**Step 1: Add failing test**

```python
def test_render_markdown_contains_expected_sections() -> None:
    from phishpicker.retro import render_markdown, compare
    preview = PreviewDoc(
        show_date="2026-04-23", venue_id=1, generated_at="2026-04-21T00:00:00Z",
        model_path="data/model.lgb",
        picks=[PreviewPick(1, "SET 1", 1, "A"), PreviewPick(2, "SET 1", 2, "B")],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A"), ActualSlot(2, "1", 2, 99, "C")]
    r = compare(preview, actual, smoke=None, venue="Sphere")
    md = render_markdown(r)
    assert md.startswith("# ")
    assert "2026-04-23" in md
    assert "## Headline" in md
    assert "## Slot-level" in md
    assert "## Where did the preview miss" in md
    assert "## Where did the preview over-commit" in md
    # table row for slot 1
    assert "| 1 | A | A |" in md or "| 1 | A | A | ✓" in md
```

**Step 2: Confirm failure.**

**Step 3: Implement**

```python
def render_markdown(retro: Retro) -> str:
    lines: list[str] = []
    venue = retro.venue or "?"
    lines.append(f"# Retro — {retro.show_date} {venue}")
    lines.append("")

    # Headline
    lines.append("## Headline")
    lines.append(f"- Preview picks: {len(retro.preview_picks)} · "
                 f"Actual slots: {len(retro.actual_slots)}")
    lines.append(f"- Set-level overlap: {len(retro.set_overlap_songs)} songs")
    exact = sum(1 for m in retro.slot_matches if m.exact_match)
    lines.append(f"- Slot-level exact matches: {exact}/{len(retro.slot_matches)}")
    smoke_summary = smoke_rank_summary(retro.smoke)
    if smoke_summary is None:
        lines.append("- Nightly-smoke: (no record)")
    else:
        n = smoke_summary["n_ranked"]
        lines.append(
            f"- Nightly-smoke: Top-1 {smoke_summary['top1']}/{n} · "
            f"Top-5 {smoke_summary['top5']}/{n} · "
            f"median rank {smoke_summary['median']}"
        )
    lines.append("")

    # Slot table
    lines.append("## Slot-level")
    lines.append("")
    lines.append("| Slot | Predicted | Actual | Match |")
    lines.append("|---|---|---|---|")
    for m in retro.slot_matches:
        mark = "✓" if m.exact_match else ""
        lines.append(f"| {m.slot_idx} | {m.predicted or '—'} | {m.actual or '—'} | {mark} |")
    lines.append("")

    # Misses: actual songs not in preview
    lines.append("## Where did the preview miss?")
    if retro.actual_only_songs:
        for name in retro.actual_only_songs:
            lines.append(f"- {name}")
    else:
        lines.append("- (none — every actual song appeared in preview)")
    lines.append("")

    # Over-commits: predicted songs that didn't appear
    lines.append("## Where did the preview over-commit?")
    if retro.preview_only_songs:
        for name in retro.preview_only_songs:
            lines.append(f"- {name}")
    else:
        lines.append("- (none — every predicted song was played)")
    lines.append("")

    return "\n".join(lines) + "\n"
```

**Step 4: Pass tests.**

**Step 5: Commit**

```bash
git commit -am "feat(retro): render_markdown — full retro document"
```

---

## Task 11: Modify `preview_night4.py` to save JSON

**Files:** modify `scripts/preview_night4.py` only. Script is thin glue;
we'll spot-verify by running it end-to-end (no unit test — the library
code inside is already reused).

**Step 1: Add import + save function**

At the top of `scripts/preview_night4.py`:

```python
import json
from datetime import datetime
```

Add after `RESIDENCY_SHOW_IDS = (...)`:

```python
PREVIEW_DIR = Path("data/previews")


def save_preview(picks: list[tuple[str, int, str]], label: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PREVIEW_DIR / f"preview-{SHOW_DATE}.json"
    payload = {
        "show_date": SHOW_DATE,
        "venue_id": VENUE_ID,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model_path": str(MODEL_PATH),
        "pass": label,
        "picks": [
            {"slot_idx": i + 1, "set": set_label, "song_id": sid, "name": name}
            for i, (set_label, sid, name) in enumerate(picks)
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path
```

**Step 2: Call it at the end of `main()`**

After the `picks_filt` line in `main()` (which is before the COMPARISON
banner), add:

```python
    saved = save_preview(picks_raw, "RAW")
    print(f"\nSaved preview JSON: {saved}")
```

Place it just before the `print("\n" + "=" * 70)` COMPARISON section so
the save happens regardless of pass divergence.

**Step 3: Spot-verify**

Run from the `api/` directory (the script expects the cwd layout used by
the existing scripts):

```bash
cd api && ~/.local/bin/uv run python ../scripts/preview_night4.py
```

Expected: script completes, prints `Saved preview JSON: data/previews/preview-2026-04-23.json`.
Verify file exists:

```bash
ls -l api/data/previews/preview-2026-04-23.json
cat api/data/previews/preview-2026-04-23.json | head -20
```

**Step 4: Commit**

```bash
git add scripts/preview_night4.py api/data/previews/preview-2026-04-23.json
git commit -m "feat(scripts): preview_night4 — save preview JSON for retro"
```

---

## Task 12: Modify `preview_residency.py` to save JSON

Mirror Task 11's pattern, but for the forward-sim (N4-N9). One file per
invocation, named by generation date.

**Step 1: Add import + save function**

At top:

```python
import json
from datetime import datetime, date as date_type
```

Add constants section:

```python
PREVIEW_DIR = Path("data/previews")
```

New function:

```python
def save_forward_sim(all_picks_by_night: dict[str, list[str]],
                    night_metadata: list[tuple[str, str, int]]) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    today = date_type.today().isoformat()
    out_path = PREVIEW_DIR / f"forward-sim-{today}.json"
    nights = []
    for night_label, show_date, show_id in night_metadata:
        names = all_picks_by_night.get(night_label, [])
        picks = [
            {"slot_idx": i + 1, "set": "", "song_id": 0, "name": name}
            for i, name in enumerate(names)
        ]
        nights.append({
            "label": night_label,
            "show_date": show_date,
            "show_id": show_id,
            "picks": picks,
        })
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model_path": str(MODEL_PATH),
        "nights": nights,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path
```

Note: `set` and `song_id` are left empty/zero because the forward-sim
loop only tracks names — keeping the schema shape uniform with
preview-{date}.json, but filling with sentinels. The retro harness only
reads `name` from the forward-sim view (it's a lower-fidelity source).

**Step 2: Call at end of `main()`**

Just before the final summary banner `"=" * 70` / "RESIDENCY PACING ANALYSIS":

```python
    saved = save_forward_sim(all_picks_by_night, NIGHTS)
    print(f"\nSaved forward-sim JSON: {saved}\n")
```

Move the save before the pacing analysis so it's captured even if the
pacing loop raises.

**Step 3: Spot-verify**

```bash
cd api && ~/.local/bin/uv run python ../scripts/preview_residency.py
ls -l api/data/previews/forward-sim-*.json
```

**Step 4: Commit**

```bash
git add scripts/preview_residency.py api/data/previews/forward-sim-*.json
git commit -m "feat(scripts): preview_residency — save forward-sim JSON for retro"
```

---

## Task 13: Create `scripts/compare_prediction_to_actual.py`

Thin glue — no unit test for the script itself.

**Step 1: Write the script**

```python
"""Retrospective: diff a saved preview against the actual setlist + nightly-smoke.

Run from the api/ directory:
    ~/.local/bin/uv run python ../scripts/compare_prediction_to_actual.py \
        --date 2026-04-23 [--retro-dir ../docs/retros]

Reads:
    data/previews/preview-<date>.json
    data/phishpicker.db
    data/nightly-predictions.jsonl  (optional)

Emits:
    stdout summary
    <retro-dir>/retro-<date>.md
"""

import argparse
import sys
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.retro import (
    compare,
    load_actual_setlist,
    load_preview,
    load_smoke_record,
    render_markdown,
    render_stdout_summary,
)

DB_PATH = Path("data/phishpicker.db")
PREVIEW_DIR = Path("data/previews")
JSONL_PATH = Path("data/nightly-predictions.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="show date, YYYY-MM-DD")
    parser.add_argument(
        "--retro-dir",
        default="../docs/retros",
        help="where to write retro markdown (default ../docs/retros)",
    )
    parser.add_argument(
        "--venue",
        default="",
        help="venue label for the retro title (e.g. 'Sphere Night 4')",
    )
    args = parser.parse_args()

    preview_path = PREVIEW_DIR / f"preview-{args.date}.json"
    if not preview_path.exists():
        print(f"ERROR: preview JSON not found: {preview_path}", file=sys.stderr)
        print(f"Run scripts/preview_night4.py first.", file=sys.stderr)
        return 1

    preview = load_preview(preview_path)

    conn = open_db(DB_PATH, read_only=True)
    actual = load_actual_setlist(conn, args.date)
    if not actual:
        print(
            f"ERROR: no setlist for {args.date} in {DB_PATH}. "
            f"Run `phishpicker ingest` first.",
            file=sys.stderr,
        )
        return 2

    smoke = load_smoke_record(JSONL_PATH, args.date)
    if smoke is None:
        print(f"NOTE: no nightly-smoke record found for {args.date} (continuing).",
              file=sys.stderr)

    retro = compare(preview, actual, smoke, venue=args.venue)
    print(render_stdout_summary(retro))

    retro_dir = Path(args.retro_dir)
    retro_dir.mkdir(parents=True, exist_ok=True)
    md_path = retro_dir / f"retro-{args.date}.md"
    md_path.write_text(render_markdown(retro))
    print(f"\nWrote retro markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 2: Spot-verify with a dummy preview**

Build a tiny preview JSON by hand and run against an existing show in
the DB (e.g., Night 1 / show_id 1764702178, show_date 2026-04-16 — which
IS in the dev DB). Verify the stdout summary prints without crashing.

```bash
# Build a minimal preview for Night 1:
cat > api/data/previews/preview-2026-04-16.json <<'EOF'
{"show_date":"2026-04-16","venue_id":1597,"generated_at":"2026-04-21T00:00:00Z",
 "model_path":"data/model.lgb","pass":"RAW",
 "picks":[{"slot_idx":1,"set":"SET 1","song_id":0,"name":"placeholder"}]}
EOF
cd api && ~/.local/bin/uv run python ../scripts/compare_prediction_to_actual.py \
  --date 2026-04-16 --venue "Sphere Night 1"
```

Expected: retro written at `docs/retros/retro-2026-04-16.md`, stdout
summary printed, no errors. (The preview is bogus but that's fine for
smoke-testing the harness.) Delete the bogus preview + retro before
committing.

**Step 3: Commit**

```bash
git add scripts/compare_prediction_to_actual.py
git commit -m "feat(scripts): compare_prediction_to_actual — retro harness CLI"
```

---

## Task 14: Lint + full test run, then wrap-up commit

**Step 1: Run ruff + pytest**

```bash
cd api && ~/.local/bin/uv run ruff check src tests
cd api && ~/.local/bin/uv run pytest -q
```

Expected: both clean. Test count: 207 + ~12 new retro tests ≈ 219.

**Step 2: If ruff fixes needed, apply + re-run.**

**Step 3: Commit any lint fixes (likely none)**

**Step 4: Final sanity: run preview_night4 for real, then compare against Night 3**

Generate the actual Night 4 preview and commit it as the locked-in
ahead-of-show prediction:

```bash
cd api && ~/.local/bin/uv run python ../scripts/preview_night4.py
cd api && ~/.local/bin/uv run python ../scripts/preview_residency.py
git add api/data/previews/
git commit -m "data: lock in v10 Night 4 preview + forward-sim before Sphere 4/23"
```

Now try the compare harness against Night 3, which IS in the DB, just to
exercise a realistic path end-to-end:

```bash
# Generate a Night 3 preview by temporarily setting SHOW_DATE="2026-04-18"
# and RESIDENCY_SHOW_IDS=(1764702178, 1764702334) in preview_night4.py,
# then running + reverting. Document the output in the wrap-up commit.
```

(Skip this step if awkward — the real test comes Friday 4/24 with
Night 4 data.)

---

## File inventory (final)

**New:**
- `api/src/phishpicker/retro.py`
- `api/tests/test_retro.py`
- `scripts/compare_prediction_to_actual.py`
- `api/data/previews/preview-2026-04-23.json` (generated)
- `api/data/previews/forward-sim-YYYY-MM-DD.json` (generated)

**Modified:**
- `scripts/preview_night4.py`
- `scripts/preview_residency.py`

**Created directories:**
- `api/data/previews/`
- `docs/retros/`
