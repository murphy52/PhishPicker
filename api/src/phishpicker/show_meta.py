"""Resolve human-facing show metadata (venue, city, state, residency run) for
a live show, keyed off its (show_date, venue_id).

Joins the canonical `shows` + `venues` tables in the read DB. The residency
logic mirrors app._residency_position (scope = same venue_id + tour_id) so the
scoreboard/bracket header and the home-screen header agree on the run badge.
"""

import sqlite3


def _residency(
    read_conn: sqlite3.Connection,
    venue_id: int,
    tour_id: int | None,
    show_date: str,
) -> tuple[int | None, int | None]:
    """(position, length) within the venue+tour residency, or (None, None)
    for a one-off (length < 2) or when tour_id is unknown."""
    if tour_id is None:
        return None, None
    length = read_conn.execute(
        "SELECT COUNT(*) FROM shows WHERE venue_id = ? AND tour_id = ?",
        (venue_id, tour_id),
    ).fetchone()[0]
    if length < 2:
        return None, None
    position = read_conn.execute(
        "SELECT COUNT(*) FROM shows "
        "WHERE venue_id = ? AND tour_id = ? AND show_date <= ?",
        (venue_id, tour_id, show_date),
    ).fetchone()[0]
    return position, length


def resolve_show_meta(
    read_conn: sqlite3.Connection, show_date: str, venue_id: int | None
) -> dict:
    """Venue/city/state + residency run for a show. Fields degrade to empty
    strings / None when the venue or canonical show isn't known — the header
    then simply renders less, never errors."""
    # Backfill venue_id from a canonical show on the same date — some live
    # shows are created without one (mirrors live_preview.build_preview).
    if venue_id is None:
        row = read_conn.execute(
            "SELECT venue_id FROM shows "
            "WHERE show_date = ? AND venue_id IS NOT NULL LIMIT 1",
            (show_date,),
        ).fetchone()
        if row:
            venue_id = row["venue_id"]

    venue = city = state = ""
    run_position: int | None = None
    run_length: int | None = None
    if venue_id is not None:
        v = read_conn.execute(
            "SELECT name, city, state FROM venues WHERE venue_id = ?", (venue_id,)
        ).fetchone()
        if v:
            venue, city, state = v["name"] or "", v["city"] or "", v["state"] or ""
        canon = read_conn.execute(
            "SELECT tour_id FROM shows WHERE show_date = ? AND venue_id = ? LIMIT 1",
            (show_date, venue_id),
        ).fetchone()
        if canon:
            run_position, run_length = _residency(
                read_conn, venue_id, canon["tour_id"], show_date
            )

    return {
        "show_date": show_date,
        "venue": venue,
        "city": city,
        "state": state,
        "run_position": run_position,
        "run_length": run_length,
    }
