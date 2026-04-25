"""Stateless preview builder — loops predict_next_stateless across all slots."""

import sqlite3

from fastapi import HTTPException

from phishpicker.model.scorer import Scorer
from phishpicker.model.stats import compute_song_stats
from phishpicker.predict import predict_next_stateless
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.extended_stats import compute_extended_stats


def _compute_hit_rank(
    *,
    read_conn: sqlite3.Connection,
    played_songs: list[int],
    target_song_id: int,
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str,
    prev_set_number: str | None,
    scorer: Scorer,
    song_ids_cache,
    song_names_cache,
    stats_cache,
    ext_cache,
    bigram_cache,
) -> int | None:
    """Return 1-based rank of `target_song_id` in the top-10 predictions, or None if absent."""
    cands = predict_next_stateless(
        read_conn=read_conn,
        played_songs=played_songs,
        current_set=current_set,
        show_date=show_date,
        venue_id=venue_id,
        prev_trans_mark=prev_trans_mark,
        prev_set_number=prev_set_number,
        top_n=10,
        scorer=scorer,
        song_ids_cache=song_ids_cache,
        song_names_cache=song_names_cache,
        stats_cache=stats_cache,
        ext_cache=ext_cache,
        bigram_cache=bigram_cache,
    )
    for i, c in enumerate(cands):
        if c["song_id"] == target_song_id:
            return i + 1
    return None


def build_preview(
    *,
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    top_k: int,
    scorer,
) -> dict:
    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if not show:
        raise HTTPException(404, "show not found")
    current_set = show["current_set"]
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
    # One-shot song name lookup — reused for both entered-slot labels and
    # for decorating scored candidates in each slot loop iteration.
    song_names = dict(read_conn.execute("SELECT song_id, name FROM songs").fetchall())
    song_ids = list(song_names.keys())

    # Per-show caches. These depend only on (show_date, venue_id, song set),
    # which are fixed across all 18 slots — so compute once, reuse.
    show_date = show["show_date"]
    venue_id = show["venue_id"]
    stats_cache = (
        compute_song_stats(read_conn, show_date, venue_id, song_ids)
        if scorer.name in ("lightgbm", "heuristic")
        else None
    )
    ext_cache = (
        compute_extended_stats(read_conn, show_date, venue_id, song_ids)
        if scorer.name == "lightgbm"
        else None
    )
    bigram_cache = (
        compute_bigram_probs(read_conn, cutoff_date=show_date)
        if scorer.name == "lightgbm"
        else None
    )

    entered_by_pos: dict[tuple[str, int], dict] = {}
    per_set_seen: dict[str, int] = {}
    for r in played_rows:
        per_set_seen[r["set_number"]] = per_set_seen.get(r["set_number"], 0) + 1
        entered_by_pos[(r["set_number"], per_set_seen[r["set_number"]])] = {
            "song_id": r["song_id"],
            "name": song_names.get(r["song_id"], f"#{r['song_id']}"),
        }

    virtual_played: list[int] = [r["song_id"] for r in played_rows]
    prev_trans_mark = played_rows[-1]["trans_mark"] if played_rows else ","
    prev_set_number: str | None = (
        played_rows[-1]["set_number"] if played_rows else None
    )

    # Per-set slot count depends on whether the set is active, past, or future
    # relative to current_set:
    #   - active (s == current_set): max(default, entered + 1). Shows the
    #     default prediction view plus one speculative set-closer once the user
    #     fills past the default (e.g. Set 1 slot 10 after 9 entered).
    #   - past (s < current_set): exactly entered. The set is closed — no more
    #     slots will be played, so drop the unused predictions. A past set with
    #     zero entered rows yields n=0 and is hidden entirely.
    #   - future (s > current_set): default. Preview what might come.
    set_order = {"1": 1, "2": 2, "E": 3}

    def _n_for(s: str, default: int) -> int:
        entered = per_set_seen.get(s, 0)
        if s == current_set:
            return max(default, entered + 1)
        if set_order.get(s, 0) < set_order.get(current_set, 0):
            return entered
        return default

    structure = [
        ("1", _n_for("1", set1)),
        ("2", _n_for("2", set2)),
        ("E", _n_for("E", enc)),
    ]
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
                show_date=show_date,
                venue_id=venue_id,
                prev_trans_mark=prev_trans_mark,
                prev_set_number=prev_set_number,
                top_n=top_k,
                scorer=scorer,
                song_ids_cache=song_ids,
                song_names_cache=song_names,
                stats_cache=stats_cache,
                ext_cache=ext_cache,
                bigram_cache=bigram_cache,
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
