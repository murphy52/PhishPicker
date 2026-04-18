"""Unified feature builder called by both training and serving.

Training calls this per (show, slot); serving calls it once per /predict.
Going through a single function guarantees training-serving parity by
construction.
"""

import sqlite3

from phishpicker.model.stats import compute_song_stats
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.context import compute_show_context
from phishpicker.train.extended_stats import compute_bustout_score, compute_extended_stats
from phishpicker.train.features import MISSING_INT, FeatureRow

SET_NUMBER_TO_INT = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 4}


def build_feature_rows(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    played_songs: list[int],
    current_set: str,
    candidate_song_ids: list[int],
    show_id: int = 0,
    bigram_cache: dict[tuple[int, int], float] | None = None,
    all_show_dates: list[str] | None = None,
) -> list[FeatureRow]:
    """Emit one FeatureRow per candidate song at the given slot.

    show_id=0 is used for live shows not yet ingested into the shows table.
    bigram_cache, if supplied, skips the per-call bigram computation — critical
    during training where we compute bigrams once per fold.
    """
    ctx = compute_show_context(conn, show_date=show_date, venue_id=venue_id)
    stats = compute_song_stats(
        conn,
        show_date,
        venue_id,
        candidate_song_ids,
        all_show_dates=all_show_dates,
    )
    ext = compute_extended_stats(conn, show_date, venue_id, candidate_song_ids)

    prev_song_id = played_songs[-1] if played_songs else MISSING_INT
    slot_number = len(played_songs) + 1
    current_set_int = SET_NUMBER_TO_INT.get(current_set, 1)

    if bigram_cache is None:
        bigram_cache = compute_bigram_probs(conn, cutoff_date=show_date)

    # run_position is a show-level column; pull once here when show_id resolves
    # to an ingested row. Live shows (show_id=0) keep the FeatureRow default.
    run_pos_row = (
        conn.execute("SELECT run_position FROM shows WHERE show_id = ?", (show_id,)).fetchone()
        if show_id
        else None
    )
    run_position_value = (
        int(run_pos_row["run_position"])
        if run_pos_row and run_pos_row["run_position"] is not None
        else 1
    )

    rows: list[FeatureRow] = []
    for sid in candidate_song_ids:
        s = stats[sid]
        e = ext[sid]
        bigram_p = (
            bigram_cache.get((prev_song_id, sid), 0.0) if prev_song_id != MISSING_INT else 0.0
        )
        row = FeatureRow.empty(song_id=sid, show_id=show_id, slot_number=slot_number)
        row.total_plays_ever = s.total_plays_ever
        row.plays_last_12mo = s.times_played_last_12mo
        row.shows_since_last_played_anywhere = (
            s.shows_since_last_played_anywhere
            if s.shows_since_last_played_anywhere is not None
            else MISSING_INT
        )
        row.shows_since_last_at_venue = (
            s.shows_since_last_played_here
            if s.shows_since_last_played_here is not None
            else MISSING_INT
        )
        row.played_already_this_run = int(s.played_already_this_run)
        row.opener_score = s.opener_score
        row.encore_score = s.encore_score
        row.middle_rate = s.middle_score
        row.current_set = current_set_int
        row.set_position = slot_number
        row.prev_song_id = prev_song_id
        row.bigram_prev_to_this = bigram_p
        row.day_of_week = ctx.day_of_week
        row.month = ctx.month
        row.era = ctx.era
        row.tour_position = ctx.tour_position

        # Extended batch: set-role refinements, venue affinity, metadata,
        # bust-out gap, days-since.
        row.set1_opener_rate = e.set1_opener_rate
        row.set2_opener_rate = e.set2_opener_rate
        row.closer_score = e.closer_score
        row.encore_rate = e.encore_rate
        row.times_at_venue = e.times_at_venue
        row.venue_debut_affinity = e.venue_debut_affinity
        row.debut_year = e.debut_year
        row.is_cover = e.is_cover
        row.days_since_last_played_anywhere = e.days_since_last_played_anywhere
        row.bustout_score = compute_bustout_score(s.shows_since_last_played_anywhere)
        row.run_position = run_position_value
        row.tour_opener_rate = e.tour_opener_rate
        row.tour_closer_rate = e.tour_closer_rate

        rows.append(row)
    return rows
