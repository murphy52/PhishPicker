"""Tests for the retrospective harness."""

import json
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
    load_preview,
)


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
