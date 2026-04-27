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
