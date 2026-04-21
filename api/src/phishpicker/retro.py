"""Retrospective harness — diff ahead-of-show previews against actual
setlists + nightly-smoke JSONL. Pure-python library; the CLI in
scripts/compare_prediction_to_actual.py is thin glue."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PreviewPick:
    slot_idx: int
    set: str
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
    slot_idx: int
    set_number: str
    position: int
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
    set_overlap_songs: list[str] = field(default_factory=list)
    preview_only_songs: list[str] = field(default_factory=list)
    actual_only_songs: list[str] = field(default_factory=list)
    slot_matches: list[SlotMatch] = field(default_factory=list)
    actual_ranks_in_preview: dict[str, int | None] = field(default_factory=dict)


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
