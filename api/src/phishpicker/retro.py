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
    seen: set[str] = set()
    overlap_ordered: list[str] = []
    for n in preview_names:
        if n in actual_set and n not in seen:
            overlap_ordered.append(n)
            seen.add(n)
    preview_only = [n for n in preview_names if n not in actual_set]
    actual_only = [n for n in actual_names if n not in preview_set]

    preview_name_to_rank = {p.name: p.slot_idx for p in preview.picks}
    actual_ranks_in_preview: dict[str, int | None] = {
        a.name: preview_name_to_rank.get(a.name) for a in actual
    }

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

    return Retro(
        show_date=preview.show_date,
        venue=venue,
        preview_picks=list(preview.picks),
        actual_slots=list(actual),
        smoke=smoke,
        set_overlap_songs=overlap_ordered,
        preview_only_songs=preview_only,
        actual_only_songs=actual_only,
        slot_matches=slot_matches,
        actual_ranks_in_preview=actual_ranks_in_preview,
    )


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


def render_stdout_summary(retro: Retro) -> str:
    lines: list[str] = []
    lines.append(f"=== Retro — {retro.show_date} {retro.venue} ===")
    lines.append(
        f"Preview picks: {len(retro.preview_picks)}  "
        f"Actual slots: {len(retro.actual_slots)}"
    )
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
