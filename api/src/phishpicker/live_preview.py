"""Stateless preview builder — loops predict_next_stateless across all slots."""

import sqlite3

from fastapi import HTTPException

from phishpicker.model.scorer import Scorer
from phishpicker.model.stats import _find_run_start, compute_song_stats
from phishpicker.predict import predict_next_stateless
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.extended_stats import compute_extended_stats


def _played_in_run(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
) -> set[int]:
    """Songs played in run-mate shows that happened before show_date.

    Returns an empty set when the live show isn't in any run (no tour
    found, no same-venue adjacent shows, or it's the first show of its run).

    Reads from both `setlist_songs` (canonical) and `live_songs` (live DB) —
    a recently-played live show may not yet be backfilled to canonical, but
    its setlist still constrains the no-repeat filter for tonight's preview.
    Live shows don't track tour_id, but the run bounds (run_start, show_date)
    are tour-derived from canonical, so any live show on a same-venue date
    within those bounds is by construction part of the same run.
    """
    if venue_id is None:
        return set()

    # Resolve tour_id: prefer the canonical shows row if the live date is
    # already pre-scheduled; fall back to the tours table by date range.
    tour_row = read_conn.execute(
        "SELECT tour_id FROM shows WHERE show_date = ? AND venue_id = ? LIMIT 1",
        (show_date, venue_id),
    ).fetchone()
    if tour_row and tour_row["tour_id"] is not None:
        tour_id = tour_row["tour_id"]
    else:
        fallback = read_conn.execute(
            "SELECT tour_id FROM tours WHERE start_date <= ? AND end_date >= ? LIMIT 1",
            (show_date, show_date),
        ).fetchone()
        if not fallback or fallback["tour_id"] is None:
            return set()
        tour_id = fallback["tour_id"]

    run_start = _find_run_start(read_conn, venue_id, show_date, tour_id=tour_id)
    if run_start == show_date:
        return set()  # first night of the run, or singleton

    canonical_rows = read_conn.execute(
        "SELECT DISTINCT ss.song_id "
        "FROM setlist_songs ss "
        "JOIN shows s ON s.show_id = ss.show_id "
        "WHERE s.venue_id = ? AND s.tour_id = ? "
        "  AND s.show_date >= ? AND s.show_date < ?",
        (venue_id, tour_id, run_start, show_date),
    ).fetchall()

    live_rows = live_conn.execute(
        "SELECT DISTINCT ls.song_id "
        "FROM live_songs ls "
        "JOIN live_show lsh ON lsh.show_id = ls.show_id "
        "WHERE lsh.venue_id = ? "
        "  AND lsh.show_date >= ? AND lsh.show_date < ?",
        (venue_id, run_start, show_date),
    ).fetchall()

    return {r["song_id"] for r in canonical_rows} | {r["song_id"] for r in live_rows}


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
    played_in_run: set[int] | None = None,
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
        played_in_run=played_in_run,
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
    show_date = show["show_date"]
    venue_id = show["venue_id"]
    # Backfill venue_id from canonical when the live row is missing it.
    # The frontend creates `/live/show` without venue_id in some flows, which
    # short-circuits the run-filter and any per-venue stats. Resolving here
    # benefits the entire prediction pipeline (compute_song_stats,
    # compute_extended_stats, the stats cache), not just the run filter.
    if venue_id is None:
        row = read_conn.execute(
            "SELECT venue_id FROM shows WHERE show_date = ? LIMIT 1",
            (show_date,),
        ).fetchone()
        if row and row["venue_id"] is not None:
            venue_id = row["venue_id"]
    meta = live_conn.execute(
        "SELECT set1_size, set2_size, encore_size FROM live_show_meta WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if meta is None:
        set1, set2, enc = 9, 7, 2
    else:
        set1, set2, enc = meta["set1_size"], meta["set2_size"], meta["encore_size"]

    played_rows = live_conn.execute(
        "SELECT song_id, set_number, trans_mark, source FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (show_id,),
    ).fetchall()
    # One-shot song name + slug lookup — reused for entered-slot labels (slug
    # decorates phish.net-verified entries with a deep link in the UI) and
    # for naming candidates in each slot loop iteration.
    song_rows = read_conn.execute("SELECT song_id, name, slug FROM songs").fetchall()
    song_names = {r["song_id"]: r["name"] for r in song_rows}
    song_slugs = {r["song_id"]: r["slug"] for r in song_rows}
    song_ids = list(song_names.keys())

    # Per-show caches. These depend only on (show_date, venue_id, song set),
    # which are fixed across all 18 slots — so compute once, reuse.
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
    # Songs played earlier in this run (prior same-venue same-tour shows).
    # Computed once per /preview call and reused across all slots.
    played_in_run = _played_in_run(read_conn, live_conn, show_date, venue_id)

    entered_by_pos: dict[tuple[str, int], dict] = {}
    per_set_seen: dict[str, int] = {}
    for r in played_rows:
        per_set_seen[r["set_number"]] = per_set_seen.get(r["set_number"], 0) + 1
        entered_by_pos[(r["set_number"], per_set_seen[r["set_number"]])] = {
            "song_id": r["song_id"],
            "name": song_names.get(r["song_id"], f"#{r['song_id']}"),
            "trans_mark": r["trans_mark"],
            "source": r["source"],
            "slug": song_slugs.get(r["song_id"]),
        }

    # Rebuilt set-by-set in the loop below. Correct iff entered songs are
    # entered in slot-iteration order — the project's UI invariant. If that
    # ever breaks, sort played_rows by (set_order, pos_within_set) before
    # building entered_by_pos.
    virtual_played: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None

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
                # Adds one top-10 prediction per entered slot. Cheap given per-show
                # caches; revisit if the hot-path latency becomes visible.
                hit_rank = _compute_hit_rank(
                    read_conn=read_conn,
                    played_songs=virtual_played,
                    target_song_id=entered["song_id"],
                    current_set=set_number,
                    show_date=show_date,
                    venue_id=venue_id,
                    prev_trans_mark=prev_trans_mark,
                    prev_set_number=prev_set_number,
                    scorer=scorer,
                    song_ids_cache=song_ids,
                    song_names_cache=song_names,
                    stats_cache=stats_cache,
                    ext_cache=ext_cache,
                    bigram_cache=bigram_cache,
                    played_in_run=played_in_run,
                )
                slots.append(
                    {
                        "slot_idx": slot_idx,
                        "set_number": set_number,
                        "position": pos,
                        "state": "entered",
                        "entered_song": {
                            "song_id": entered["song_id"],
                            "name": entered["name"],
                            "source": entered["source"],
                            "slug": entered["slug"],
                        },
                        "hit_rank": hit_rank,
                    }
                )
                virtual_played = virtual_played + [entered["song_id"]]
                prev_trans_mark = entered["trans_mark"]
                prev_set_number = set_number
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
                played_in_run=played_in_run,
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
