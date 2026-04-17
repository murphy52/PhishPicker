import sqlite3
from datetime import UTC, datetime


def upsert_show(conn: sqlite3.Connection, show: dict) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(show_id) DO UPDATE SET
            show_date = excluded.show_date,
            venue_id = excluded.venue_id,
            tour_id = excluded.tour_id,
            fetched_at = excluded.fetched_at
        """,
        (show["showid"], show["showdate"], show.get("venueid"), show.get("tourid"), now),
    )
    conn.commit()


def upsert_setlist_songs(conn: sqlite3.Connection, setlist: list[dict]) -> int:
    """Replace a show's setlist atomically.

    DELETE+INSERT so phish.net corrections that remove a row don't leave orphans.
    """
    if not setlist:
        return 0
    show_ids = {row["showid"] for row in setlist}
    with conn:
        for sid in show_ids:
            conn.execute("DELETE FROM setlist_songs WHERE show_id = ?", (sid,))
        conn.executemany(
            """
            INSERT INTO setlist_songs
                (show_id, set_number, position, song_id, trans_mark)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    row["showid"],
                    # phish.net uses lowercase 'e' for encore; the schema
                    # CHECK constraint requires uppercase 'E'. Normalize here
                    # so the rest of the codebase can assume upper-case.
                    str(row["set"]).upper(),
                    int(row["position"]),
                    row["songid"],
                    row.get("trans_mark") or ",",
                )
                for row in setlist
            ],
        )
    return len(setlist)
