"""Retrospective harness — diff ahead-of-show previews against actual
setlists + nightly-smoke JSONL. Pure-python library; the CLI in
scripts/compare_prediction_to_actual.py is thin glue."""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

_SET_ORDER = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}


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


def load_actual_setlist(conn: sqlite3.Connection, show_date: str) -> list[ActualSlot]:
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
    rows = sorted(
        rows,
        key=lambda r: (_SET_ORDER.get(str(r["set_number"]).upper(), 99), r["position"]),
    )
    return [
        ActualSlot(
            slot_idx=i + 1,
            set_number=r["set_number"],
            position=r["position"],
            song_id=r["song_id"],
            name=r["name"],
        )
        for i, r in enumerate(rows)
    ]


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
