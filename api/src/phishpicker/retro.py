"""Retrospective harness — diff ahead-of-show previews against actual
setlists + nightly-smoke JSONL. Pure-python library; the CLI in
scripts/compare_prediction_to_actual.py is thin glue."""

from dataclasses import dataclass, field


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
