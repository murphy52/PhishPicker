import bisect
import sqlite3

from phishpicker.model.heuristic import SongStats


def _find_run_start(
    conn: sqlite3.Connection,
    venue_id: int | None,
    show_date: str,
    tour_id: int | None = None,
) -> str:
    """Walk backwards through scheduled shows until the venue changes.

    A run is an unbroken chronological sequence of shows at the same venue.
    Any-length gap is tolerated so long as no other venue appears in between
    — this correctly spans residencies like Phish's 9-show Sphere run that
    contain multi-day off-blocks between weekends.

    When `tour_id` is supplied, the walk is constrained to the same tour:
    two same-venue runs separated by a different tour are not glued together
    (e.g. spring and fall Hampton stands).
    """
    if venue_id is None:
        return show_date
    start = show_date
    cur = show_date
    while True:
        if tour_id is not None:
            row = conn.execute(
                "SELECT show_date, venue_id FROM shows "
                "WHERE show_date < ? AND tour_id = ? "
                "ORDER BY show_date DESC LIMIT 1",
                (cur, tour_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT show_date, venue_id FROM shows "
                "WHERE show_date < ? ORDER BY show_date DESC LIMIT 1",
                (cur,),
            ).fetchone()
        if not row or row["venue_id"] != venue_id:
            return start
        start = row["show_date"]
        cur = row["show_date"]


def _find_run_end(
    conn: sqlite3.Connection,
    venue_id: int | None,
    show_date: str,
    tour_id: int | None = None,
) -> str:
    """Forward analog of `_find_run_start`: walks forward through scheduled
    shows until the venue changes.

    Relies on phish.net future-show placeholders being ingested (they are —
    `/shows.json` returns future shows with no setlist). For live predictions
    at an unscheduled date, returns show_date unchanged.
    """
    if venue_id is None:
        return show_date
    end = show_date
    cur = show_date
    while True:
        if tour_id is not None:
            row = conn.execute(
                "SELECT show_date, venue_id FROM shows "
                "WHERE show_date > ? AND tour_id = ? "
                "ORDER BY show_date ASC LIMIT 1",
                (cur, tour_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT show_date, venue_id FROM shows "
                "WHERE show_date > ? ORDER BY show_date ASC LIMIT 1",
                (cur,),
            ).fetchone()
        if not row or row["venue_id"] != venue_id:
            return end
        end = row["show_date"]
        cur = row["show_date"]


def find_run_bounds(
    conn: sqlite3.Connection,
    venue_id: int | None,
    show_date: str,
    tour_id: int | None = None,
) -> tuple[str, str, int, int]:
    """(run_start, run_end, run_position, run_length_total).

    run_position is 1-indexed: if show_date is the first show of the run,
    run_position=1. run_length_total counts shows (including show_date
    itself). Inclusive of show_date in run_length if it has a record OR is
    the live show being predicted.
    """
    if venue_id is None:
        return (show_date, show_date, 1, 1)
    start = _find_run_start(conn, venue_id, show_date, tour_id=tour_id)
    end = _find_run_end(conn, venue_id, show_date, tour_id=tour_id)
    if tour_id is not None:
        shows_in_run = [
            r[0]
            for r in conn.execute(
                "SELECT show_date FROM shows "
                "WHERE venue_id = ? AND tour_id = ? AND show_date BETWEEN ? AND ? "
                "ORDER BY show_date",
                (venue_id, tour_id, start, end),
            )
        ]
    else:
        shows_in_run = [
            r[0]
            for r in conn.execute(
                "SELECT show_date FROM shows "
                "WHERE venue_id = ? AND show_date BETWEEN ? AND ? "
                "ORDER BY show_date",
                (venue_id, start, end),
            )
        ]
    # If show_date isn't ingested (live show), pretend it's appended so
    # run_length includes tonight.
    if show_date not in shows_in_run:
        shows_in_run.append(show_date)
        shows_in_run.sort()
    run_position = shows_in_run.index(show_date) + 1
    return (start, end, run_position, len(shows_in_run))


def compute_song_stats(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    song_ids: list[int],
    all_show_dates: list[str] | None = None,
    tour_id: int | None = None,
) -> dict[int, SongStats]:
    """Compute SongStats for song_ids as of show_date (strictly before).

    played_already_this_run is computed live from venue+date adjacency,
    NOT from shows.run_position — the latter is stale for the live show.
    """
    placeholders = ",".join("?" * len(song_ids))

    # Play-count fields use COUNT(DISTINCT show_id) so Phish "sandwiches"
    # (same song twice in one show, e.g. Fuego → Golden Age → Fuego) count
    # as one performance, not two. Otherwise ~34% of historical shows
    # double-count at least one song.
    total_plays = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(DISTINCT ss.show_id) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
            GROUP BY ss.song_id
            """,
            [*song_ids, show_date],
        ).fetchall()
    )

    last_12mo_counts = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(DISTINCT ss.show_id) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders})
              AND s.show_date < ?
              AND s.show_date >= date(?, '-1 year')
            GROUP BY ss.song_id
            """,
            [*song_ids, show_date, show_date],
        ).fetchall()
    )

    last_played_anywhere = dict(
        conn.execute(
            f"""
            SELECT song_id, MAX(show_date) AS last_date
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE song_id IN ({placeholders}) AND show_date < ?
            GROUP BY song_id
            """,
            [*song_ids, show_date],
        ).fetchall()
    )
    last_played_here: dict[int, str] = {}
    if venue_id is not None:
        last_played_here = dict(
            conn.execute(
                f"""
                SELECT song_id, MAX(show_date) AS last_date
                FROM setlist_songs ss JOIN shows s USING (show_id)
                WHERE song_id IN ({placeholders})
                  AND show_date < ? AND s.venue_id = ?
                GROUP BY song_id
                """,
                [*song_ids, show_date, venue_id],
            ).fetchall()
        )

    # Pull the full sorted show_date list once per call (tiny — ~5000 rows in
    # 2026) and use bisect for O(log N) lookup. Previously this was a DB query
    # per (song, call) pair, which scaled to ~1B queries on a full walk-forward
    # training run. Callers that amortize across many calls can pass in the
    # list themselves.
    if all_show_dates is None:
        all_show_dates = [r[0] for r in conn.execute("SELECT show_date FROM shows")]
        all_show_dates.sort()
    _show_idx = bisect.bisect_left(all_show_dates, show_date)

    def shows_between(from_date: str) -> int:
        # Count shows with `from_date < show_date_row < show_date`.
        left = bisect.bisect_right(all_show_dates, from_date)
        return max(0, _show_idx - left)

    # Role rates are show-rather-than-row counts so a sandwich-encore (rare
    # but legal) doesn't inflate either the encore numerator or the total
    # denominator. Opener can't naturally double-count (PK forbids two rows
    # at set 1 position 1) but using COUNT(DISTINCT) here keeps the metric
    # consistent.
    role_rows = conn.execute(
        f"""
        SELECT
            ss.song_id,
            COUNT(DISTINCT CASE WHEN ss.set_number='1' AND ss.position=1
                                THEN ss.show_id END) AS opener,
            COUNT(DISTINCT CASE WHEN ss.set_number='E'
                                THEN ss.show_id END) AS encore,
            COUNT(DISTINCT ss.show_id) AS total
        FROM setlist_songs ss JOIN shows s USING (show_id)
        WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
        GROUP BY ss.song_id
        """,
        [*song_ids, show_date],
    ).fetchall()
    roles = {
        r["song_id"]: {
            "opener": (r["opener"] or 0) / max(1, r["total"] or 1),
            "encore": (r["encore"] or 0) / max(1, r["total"] or 1),
            "middle": 1.0 - ((r["opener"] or 0) + (r["encore"] or 0)) / max(1, r["total"] or 1),
        }
        for r in role_rows
    }

    plays_this_run: dict[int, int] = {}
    if venue_id is not None:
        run_start = _find_run_start(conn, venue_id, show_date, tour_id=tour_id)
        if run_start < show_date:
            plays_this_run = {
                r["song_id"]: r["n"]
                for r in conn.execute(
                    """
                    SELECT ss.song_id, COUNT(DISTINCT ss.show_id) AS n
                    FROM setlist_songs ss JOIN shows s USING (show_id)
                    WHERE s.venue_id = ? AND s.show_date >= ? AND s.show_date < ?
                    GROUP BY ss.song_id
                    """,
                    (venue_id, run_start, show_date),
                ).fetchall()
            }

    result: dict[int, SongStats] = {}
    for sid in song_ids:
        last_anywhere = last_played_anywhere.get(sid)
        last_here = last_played_here.get(sid)
        r = roles.get(sid, {"opener": 0.0, "encore": 0.0, "middle": 1.0})
        result[sid] = SongStats(
            song_id=sid,
            times_played_last_12mo=last_12mo_counts.get(sid, 0),
            total_plays_ever=total_plays.get(sid, 0),
            shows_since_last_played_anywhere=shows_between(last_anywhere)
            if last_anywhere
            else None,
            shows_since_last_played_here=shows_between(last_here) if last_here else None,
            played_already_this_run=sid in plays_this_run,
            plays_this_run_count=plays_this_run.get(sid, 0),
            opener_score=r["opener"],
            encore_score=r["encore"],
            middle_score=r["middle"],
        )
    return result
