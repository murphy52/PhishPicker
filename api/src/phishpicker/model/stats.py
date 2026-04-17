import sqlite3
from datetime import date, timedelta

from phishpicker.model.heuristic import SongStats


def _find_run_start(conn: sqlite3.Connection, venue_id: int | None, show_date: str) -> str:
    """Walk backwards day-by-day from show_date to find the earliest consecutive-day show.
    A gap > 1 day ends the run. Used for live shows not yet ingested."""
    if venue_id is None:
        return show_date
    cur = date.fromisoformat(show_date)
    while True:
        prev = cur - timedelta(days=1)
        prior = conn.execute(
            "SELECT show_date FROM shows WHERE venue_id = ? AND show_date = ?",
            (venue_id, prev.isoformat()),
        ).fetchone()
        if not prior:
            return cur.isoformat()
        cur = prev


def compute_song_stats(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    song_ids: list[int],
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

    def shows_between(from_date: str) -> int:
        r = conn.execute(
            "SELECT COUNT(*) FROM shows WHERE show_date > ? AND show_date < ?",
            (from_date, show_date),
        ).fetchone()
        return int(r[0])

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
        run_start = _find_run_start(conn, venue_id, show_date)
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
            shows_since_last_played_anywhere=shows_between(last_anywhere) if last_anywhere else None,
            shows_since_last_played_here=shows_between(last_here) if last_here else None,
            played_already_this_run=sid in played_this_run,
            opener_score=r["opener"],
            encore_score=r["encore"],
            middle_score=r["middle"],
        )
    return result
