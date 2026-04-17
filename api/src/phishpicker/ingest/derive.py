import sqlite3
from datetime import date


def recompute_run_and_tour_positions(conn: sqlite3.Connection) -> None:
    """Recompute run_position / run_length / tour_position for all shows.

    A 'run' is consecutive-day shows at the same venue (gap <= 1 day).
    """
    rows = conn.execute(
        "SELECT show_id, show_date, venue_id, tour_id FROM shows ORDER BY show_date, show_id"
    ).fetchall()

    current_run: list[tuple[int, str, int]] = []

    def flush() -> None:
        if not current_run:
            return
        ids = [t[0] for t in current_run]
        run_len = len(ids)
        for pos, sid in enumerate(ids, start=1):
            conn.execute(
                "UPDATE shows SET run_position = ?, run_length = ? WHERE show_id = ?",
                (pos, run_len, sid),
            )

    prev = None
    for r in rows:
        sid, sdate, vid = r["show_id"], r["show_date"], r["venue_id"]
        if (
            prev
            and vid is not None
            and prev[2] == vid
            and (date.fromisoformat(sdate) - date.fromisoformat(prev[1])).days <= 1
        ):
            current_run.append((sid, sdate, vid))
        else:
            flush()
            current_run = [(sid, sdate, vid)]
        prev = (sid, sdate, vid)
    flush()

    # tour positions
    tour_rows = conn.execute(
        "SELECT show_id, tour_id FROM shows WHERE tour_id IS NOT NULL "
        "ORDER BY tour_id, show_date, show_id"
    ).fetchall()
    per_tour: dict[int, int] = {}
    for r in tour_rows:
        per_tour[r["tour_id"]] = per_tour.get(r["tour_id"], 0) + 1
        conn.execute(
            "UPDATE shows SET tour_position = ? WHERE show_id = ?",
            (per_tour[r["tour_id"]], r["show_id"]),
        )
    conn.commit()
