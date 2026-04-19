import bisect
import sqlite3
from datetime import date, timedelta

from phishpicker.model.heuristic import SongStats

_RUN_MAX_GAP_DAYS = 2  # one off-night is still "the same run"


def _find_run_start(
    conn: sqlite3.Connection,
    venue_id: int | None,
    show_date: str,
    tour_id: int | None = None,
) -> str:
    """Walk backwards to find the earliest show of the current multi-night run.

    Relaxed from the original gap=1 rule to gap≤2 (one off-night tolerated)
    AND, when `tour_id` is supplied, constrained to the same tour. This makes
    residencies like Phish's 9-show Sphere run (which always contains off-
    nights between weekends) register as a single run so `played_already_this_run`
    correctly excludes everything played earlier in the residency.
    """
    if venue_id is None:
        return show_date
    cur = date.fromisoformat(show_date)
    while True:
        window_start = cur - timedelta(days=_RUN_MAX_GAP_DAYS)
        if tour_id is not None:
            row = conn.execute(
                "SELECT MAX(show_date) FROM shows "
                "WHERE venue_id = ? AND tour_id = ? "
                "AND show_date >= ? AND show_date < ?",
                (venue_id, tour_id, window_start.isoformat(), cur.isoformat()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(show_date) FROM shows "
                "WHERE venue_id = ? AND show_date >= ? AND show_date < ?",
                (venue_id, window_start.isoformat(), cur.isoformat()),
            ).fetchone()
        prior_date = row[0] if row else None
        if not prior_date:
            return cur.isoformat()
        cur = date.fromisoformat(prior_date)


def _find_run_end(
    conn: sqlite3.Connection,
    venue_id: int | None,
    show_date: str,
    tour_id: int | None = None,
) -> str:
    """Forward analog of `_find_run_start`: the latest scheduled show of this run.

    Relies on phish.net future-show placeholders being ingested (they are —
    `/shows.json` returns future shows with no setlist). For live predictions
    at an unscheduled date, returns show_date unchanged.
    """
    if venue_id is None:
        return show_date
    cur = date.fromisoformat(show_date)
    while True:
        window_end = cur + timedelta(days=_RUN_MAX_GAP_DAYS)
        if tour_id is not None:
            row = conn.execute(
                "SELECT MIN(show_date) FROM shows "
                "WHERE venue_id = ? AND tour_id = ? "
                "AND show_date > ? AND show_date <= ?",
                (venue_id, tour_id, cur.isoformat(), window_end.isoformat()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MIN(show_date) FROM shows "
                "WHERE venue_id = ? AND show_date > ? AND show_date <= ?",
                (venue_id, cur.isoformat(), window_end.isoformat()),
            ).fetchone()
        next_date = row[0] if row else None
        if not next_date:
            return cur.isoformat()
        cur = date.fromisoformat(next_date)


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

    total_plays = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(*) AS n
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
            SELECT ss.song_id, COUNT(*) AS n
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

    role_rows = conn.execute(
        f"""
        SELECT
            ss.song_id,
            SUM(CASE WHEN ss.set_number='1' AND ss.position=1 THEN 1 ELSE 0 END) AS opener,
            SUM(CASE WHEN ss.set_number='E' THEN 1 ELSE 0 END) AS encore,
            COUNT(*) AS total
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

    played_this_run: set[int] = set()
    if venue_id is not None:
        run_start = _find_run_start(conn, venue_id, show_date, tour_id=tour_id)
        if run_start < show_date:
            played_this_run = {
                r["song_id"]
                for r in conn.execute(
                    """
                    SELECT DISTINCT ss.song_id FROM setlist_songs ss
                    JOIN shows s USING (show_id)
                    WHERE s.venue_id = ? AND s.show_date >= ? AND s.show_date < ?
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
            played_already_this_run=sid in played_this_run,
            opener_score=r["opener"],
            encore_score=r["encore"],
            middle_score=r["middle"],
        )
    return result
