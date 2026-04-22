"""Stateless preview builder — loops predict_next_stateless across all slots."""

import sqlite3

from fastapi import HTTPException

from phishpicker.predict import predict_next_stateless


def build_preview(
    *,
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    top_k: int,
    scorer,
) -> dict:
    show = live_conn.execute(
        "SELECT show_date, venue_id FROM live_show WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if not show:
        raise HTTPException(404, "show not found")
    meta = live_conn.execute(
        "SELECT set1_size, set2_size, encore_size FROM live_show_meta WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if meta is None:
        set1, set2, enc = 9, 7, 2
    else:
        set1, set2, enc = meta["set1_size"], meta["set2_size"], meta["encore_size"]

    played_rows = live_conn.execute(
        "SELECT song_id, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (show_id,),
    ).fetchall()
    played_names = (
        dict(read_conn.execute("SELECT song_id, name FROM songs").fetchall())
        if played_rows
        else {}
    )

    entered_by_pos: dict[tuple[str, int], dict] = {}
    per_set_seen: dict[str, int] = {}
    for r in played_rows:
        per_set_seen[r["set_number"]] = per_set_seen.get(r["set_number"], 0) + 1
        entered_by_pos[(r["set_number"], per_set_seen[r["set_number"]])] = {
            "song_id": r["song_id"],
            "name": played_names.get(r["song_id"], f"#{r['song_id']}"),
        }

    virtual_played: list[int] = [r["song_id"] for r in played_rows]
    prev_trans_mark = played_rows[-1]["trans_mark"] if played_rows else ","
    prev_set_number: str | None = (
        played_rows[-1]["set_number"] if played_rows else None
    )

    structure = [("1", set1), ("2", set2), ("E", enc)]
    slots = []
    slot_idx = 0
    for set_number, n in structure:
        for pos in range(1, n + 1):
            slot_idx += 1
            entered = entered_by_pos.get((set_number, pos))
            if entered:
                slots.append(
                    {
                        "slot_idx": slot_idx,
                        "set_number": set_number,
                        "position": pos,
                        "state": "entered",
                        "entered_song": entered,
                    }
                )
                continue
            cands = predict_next_stateless(
                read_conn=read_conn,
                played_songs=virtual_played,
                current_set=set_number,
                show_date=show["show_date"],
                venue_id=show["venue_id"],
                prev_trans_mark=prev_trans_mark,
                prev_set_number=prev_set_number,
                top_n=top_k,
                scorer=scorer,
            )
            slots.append(
                {
                    "slot_idx": slot_idx,
                    "set_number": set_number,
                    "position": pos,
                    "state": "predicted",
                    "top_k": [{**c, "rank": i + 1} for i, c in enumerate(cands)],
                }
            )
            if cands:
                virtual_played = virtual_played + [cands[0]["song_id"]]
                prev_trans_mark = ","
                prev_set_number = set_number
    return {"slots": slots}
