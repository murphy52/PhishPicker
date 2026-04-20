"""Unified feature builder called by both training and serving.

Training calls this per (show, slot); serving calls it once per /predict.
Going through a single function guarantees training-serving parity by
construction.
"""

import sqlite3

from phishpicker.model.stats import compute_song_stats, find_run_bounds
from phishpicker.train.albums import days_between, latest_album_as_of, song_album_map
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.context import compute_show_context
from phishpicker.train.extended_stats import compute_bustout_score, compute_extended_stats
from phishpicker.train.features import MISSING_INT, FeatureRow

SET_NUMBER_TO_INT = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 4}
SEGUE_MARK_TO_INT = {",": 0, ">": 1, "->": 2}


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
    prev_trans_mark: str = ",",
) -> list[FeatureRow]:
    """Emit one FeatureRow per candidate song at the given slot.

    show_id=0 is used for live shows not yet ingested into the shows table.
    bigram_cache, if supplied, skips the per-call bigram computation — critical
    during training where we compute bigrams once per fold.
    """
    ctx = compute_show_context(conn, show_date=show_date, venue_id=venue_id)
    # Resolve tour_id: if show_id is populated (training, or a live show whose
    # row already exists), read shows.tour_id directly. Otherwise fall back to
    # the date-range match via tours.start_date/end_date (sparse today — stubs
    # omit dates — but useful once we ingest real tour metadata).
    tour_id: int | None = None
    if show_id:
        r = conn.execute("SELECT tour_id FROM shows WHERE show_id = ?", (show_id,)).fetchone()
        if r and r["tour_id"] is not None:
            tour_id = int(r["tour_id"])
    if tour_id is None:
        r = conn.execute(
            "SELECT tour_id FROM tours "
            "WHERE start_date IS NOT NULL AND end_date IS NOT NULL "
            "AND start_date <= ? AND end_date >= ? LIMIT 1",
            (show_date, show_date),
        ).fetchone()
        if r:
            tour_id = int(r["tour_id"])

    stats = compute_song_stats(
        conn,
        show_date,
        venue_id,
        candidate_song_ids,
        all_show_dates=all_show_dates,
        tour_id=tour_id,
    )
    ext = compute_extended_stats(
        conn,
        show_date,
        venue_id,
        candidate_song_ids,
        tour_id=tour_id,
        all_show_dates=all_show_dates,
    )

    prev_song_id = played_songs[-1] if played_songs else MISSING_INT
    slot_number = len(played_songs) + 1
    current_set_int = SET_NUMBER_TO_INT.get(current_set, 1)

    if bigram_cache is None:
        bigram_cache = compute_bigram_probs(conn, cutoff_date=show_date)

    # run_position + run_length_total via find_run_bounds — also handles live
    # shows (no show_id row yet) by date-adjacency walk with tour_id constraint.
    _, _, run_position_value, run_length_value = find_run_bounds(
        conn, venue_id=venue_id, show_date=show_date, tour_id=tour_id
    )
    frac_run_remaining_value = (
        (run_length_value - run_position_value) / run_length_value if run_length_value else 0.0
    )

    # Album-era context — same for every candidate on the same show.
    latest_album = latest_album_as_of(show_date)
    days_since_album_value = (
        days_between(latest_album.release_date, show_date) if latest_album else MISSING_INT
    )
    song_to_album = song_album_map(conn, candidate_song_ids)

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
        row.run_length_total = run_length_value
        row.frac_run_remaining = frac_run_remaining_value
        row.tour_opener_rate = e.tour_opener_rate
        row.tour_closer_rate = e.tour_closer_rate
        row.times_this_tour = e.times_this_tour
        row.shows_since_last_played_this_tour = e.shows_since_last_played_this_tour
        row.segue_mark_in = SEGUE_MARK_TO_INT.get(prev_trans_mark, 0)
        row.shows_since_last_set1_opener = e.shows_since_last_set1_opener
        row.shows_since_last_any_opener_role = e.shows_since_last_any_opener_role
        row.avg_set_position_when_played = e.avg_set_position_when_played
        # Album-recency batch (days_since_debut dropped in v6).
        row.plays_last_6mo = e.plays_last_6mo
        row.recent_play_acceleration = e.recent_play_acceleration
        row.days_since_last_new_album = days_since_album_value
        song_alb = song_to_album.get(sid)
        row.is_from_latest_album = (
            1
            if song_alb is not None
            and latest_album is not None
            and song_alb.album_id == latest_album.album_id
            else 0
        )

        rows.append(row)
    return rows
