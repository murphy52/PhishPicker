"""Tests for the retrospective harness."""

import json
import sqlite3
from pathlib import Path

import pytest

from phishpicker.retro import (
    ActualSlot,
    PreviewDoc,
    PreviewPick,
    Retro,
    SlotMatch,
    SmokeRecord,
    SmokeSlotRank,
    compare,
    load_actual_setlist,
    load_preview,
    load_smoke_record,
    render_markdown,
    render_stdout_summary,
    smoke_rank_summary,
)


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


def test_module_imports() -> None:
    PreviewPick(slot_idx=1, set="SET 1", song_id=1, name="x")
    PreviewDoc(show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p", picks=[])
    ActualSlot(slot_idx=1, set_number="1", position=1, song_id=1, name="x")
    SmokeSlotRank(slot=1, actual_song="x", actual_rank=5)
    SmokeRecord(date="2026-04-23", show_id=1, venue="v", slots=[])
    SlotMatch(slot_idx=1, predicted="x", actual="x", exact_match=True)
    Retro(show_date="2026-04-23", venue="v", preview_picks=[], actual_slots=[], smoke=None)


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


def test_load_actual_setlist_returns_slots_in_order() -> None:
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
    assert slots[2].slot_idx == 3


def test_load_actual_setlist_missing_show_returns_empty() -> None:
    conn = _make_db()
    assert load_actual_setlist(conn, "1999-01-01") == []


def test_load_smoke_record_finds_matching_date(tmp_path: Path) -> None:
    jsonl = tmp_path / "smoke.jsonl"
    rec1 = {
        "date": "2026-04-16",
        "show_id": 1,
        "venue": "Sphere",
        "slots": [{"slot": 1, "actual_song": "Sample in a Jar", "actual_rank": 7}],
    }
    rec2 = {
        "date": "2026-04-23",
        "show_id": 2,
        "venue": "Sphere",
        "slots": [
            {"slot": 1, "actual_song": "Buried Alive", "actual_rank": 1},
            {"slot": 2, "actual_song": "Moma Dance", "actual_rank": 4},
        ],
    }
    jsonl.write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n")

    rec = load_smoke_record(jsonl, "2026-04-23")
    assert rec is not None
    assert rec.show_id == 2
    assert len(rec.slots) == 2
    assert rec.slots[0].actual_rank == 1


def test_load_smoke_record_missing_date_returns_none(tmp_path: Path) -> None:
    jsonl = tmp_path / "smoke.jsonl"
    jsonl.write_text(
        json.dumps({"date": "2025-01-01", "show_id": 1, "venue": "x", "slots": []}) + "\n"
    )
    assert load_smoke_record(jsonl, "2026-04-23") is None


def test_load_smoke_record_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_smoke_record(tmp_path / "nope.jsonl", "2026-04-23") is None


def test_compare_set_level_overlap() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "Buried Alive"),
            PreviewPick(2, "SET 1", 2, "Moma Dance"),
            PreviewPick(3, "SET 2", 3, "Oblivion"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 1, "Buried Alive"),
        ActualSlot(2, "1", 2, 99, "Sample in a Jar"),
        ActualSlot(3, "2", 1, 3, "Oblivion"),
    ]
    r = compare(preview, actual, smoke=None)
    assert set(r.set_overlap_songs) == {"Buried Alive", "Oblivion"}
    assert r.preview_only_songs == ["Moma Dance"]
    assert r.actual_only_songs == ["Sample in a Jar"]


def test_compare_slot_level_match() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "A"),
            PreviewPick(2, "SET 1", 2, "B"),
            PreviewPick(3, "SET 1", 3, "C"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 1, "A"),
        ActualSlot(2, "1", 2, 99, "X"),
        ActualSlot(3, "1", 3, 3, "C"),
    ]
    r = compare(preview, actual, smoke=None)
    assert len(r.slot_matches) == 3
    assert r.slot_matches[0].exact_match
    assert not r.slot_matches[1].exact_match
    assert r.slot_matches[2].exact_match
    assert r.slot_matches[1].predicted == "B"
    assert r.slot_matches[1].actual == "X"


def test_compare_rank_of_actual_in_preview() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "A"),
            PreviewPick(2, "SET 1", 2, "B"),
            PreviewPick(3, "SET 1", 3, "C"),
        ],
    )
    actual = [
        ActualSlot(1, "1", 1, 3, "C"),
        ActualSlot(2, "1", 2, 99, "X"),
    ]
    r = compare(preview, actual, smoke=None)
    assert r.actual_ranks_in_preview["C"] == 3
    assert r.actual_ranks_in_preview["X"] is None


def test_compare_slot_mismatch_in_length() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[
            PreviewPick(1, "SET 1", 1, "A"),
            PreviewPick(2, "SET 1", 2, "B"),
        ],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A")]
    r = compare(preview, actual, smoke=None)
    assert len(r.slot_matches) == 2
    assert r.slot_matches[1].predicted == "B"
    assert r.slot_matches[1].actual is None
    assert not r.slot_matches[1].exact_match


def test_smoke_rank_summary() -> None:
    smoke = SmokeRecord(
        date="2026-04-23",
        show_id=1,
        venue="Sphere",
        slots=[
            SmokeSlotRank(slot=1, actual_song="A", actual_rank=1),
            SmokeSlotRank(slot=2, actual_song="B", actual_rank=4),
            SmokeSlotRank(slot=3, actual_song="C", actual_rank=7),
            SmokeSlotRank(slot=4, actual_song="D", actual_rank=None),
        ],
    )
    s = smoke_rank_summary(smoke)
    assert s is not None
    assert s["n_ranked"] == 3
    assert s["top1"] == 1
    assert s["top5"] == 2
    assert s["top10"] == 3
    assert s["median"] == 4


def test_smoke_rank_summary_none_input() -> None:
    assert smoke_rank_summary(None) is None


def test_render_stdout_summary_basic() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[PreviewPick(1, "SET 1", 1, "A"), PreviewPick(2, "SET 1", 2, "B")],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A"), ActualSlot(2, "1", 2, 99, "C")]
    smoke = SmokeRecord(
        date="2026-04-23",
        show_id=1,
        venue="Sphere",
        slots=[SmokeSlotRank(1, "A", 1), SmokeSlotRank(2, "C", 12)],
    )
    r = compare(preview, actual, smoke, venue="Sphere")
    out = render_stdout_summary(r)
    assert "2026-04-23" in out
    assert "Sphere" in out
    assert "Top-1" in out


def test_render_stdout_summary_without_smoke() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="t",
        model_path="p",
        picks=[PreviewPick(1, "SET 1", 1, "A")],
    )
    actual = [ActualSlot(1, "1", 1, 1, "A")]
    r = compare(preview, actual, smoke=None, venue="Sphere")
    out = render_stdout_summary(r)
    assert out
    assert "smoke" in out.lower() or "nightly" in out.lower()


def test_render_markdown_contains_expected_sections() -> None:
    preview = PreviewDoc(
        show_date="2026-04-23",
        venue_id=1,
        generated_at="2026-04-21T00:00:00Z",
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
    assert "| 1 | A | A |" in md
