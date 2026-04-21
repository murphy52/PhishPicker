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
    PreviewPick(slot_idx=1, set="SET 1", song_id=1, name="x")
    PreviewDoc(show_date="2026-04-23", venue_id=1, generated_at="t", model_path="p", picks=[])
    ActualSlot(slot_idx=1, set_number="1", position=1, song_id=1, name="x")
    SmokeSlotRank(slot=1, actual_song="x", actual_rank=5)
    SmokeRecord(date="2026-04-23", show_id=1, venue="v", slots=[])
    SlotMatch(slot_idx=1, predicted="x", actual="x", exact_match=True)
    Retro(show_date="2026-04-23", venue="v", preview_picks=[], actual_slots=[], smoke=None)
