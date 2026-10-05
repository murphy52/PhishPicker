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
    """Replace each show's stored setlist with phish.net's, unless they match.

    DELETE+INSERT so phish.net corrections that remove a row don't leave orphans.
    Both run inside one transaction (`with conn:` — sqlite3 opens it at the
    DELETE and commits on exit, or rolls back on error), so another connection
    sees the old setlist until the new one is complete, never an empty show.
    A show whose stored rows already match is left alone: no DELETE, no
    INSERT, no write lock.

    Stubs any song_id missing from the songs table using the setlist row's
    `song` name — phish.net's songs.json list doesn't always include every
    songid referenced by setlists (aliases / deprecated / typos).

    Returns the number of setlist rows written (0 when nothing changed).
    """
    if not setlist:
        return 0
    now = datetime.now(UTC).isoformat()
    # Dedupe on (show_id, set, position). phish.net occasionally ships
    # duplicate slot rows in a setlist (ambiguous entries for old shows).
    # Keeping the last wins; the difference between duplicates is typically
    # just a trans_mark variant.
    deduped: dict[tuple[int, str, int], dict] = {}
    for row in setlist:
        key = (row["showid"], str(row["set"]).upper(), int(row["position"]))
        deduped[key] = row
    by_show: dict[int, list[dict]] = {}
    for row in deduped.values():
        by_show.setdefault(row["showid"], []).append(row)

    written = 0
    with conn:
        for sid, rows in by_show.items():
            slots = [_slot(row) for row in rows]
            if set(slots) == _stored_slots(conn, sid):
                continue
            conn.execute("DELETE FROM setlist_songs WHERE show_id = ?", (sid,))
            for row in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO songs (song_id, name, first_seen_at) VALUES (?, ?, ?)",
                    (row["songid"], row.get("song") or f"#{row['songid']}", now),
                )
            conn.executemany(
                """
                INSERT INTO setlist_songs
                    (show_id, set_number, position, song_id, trans_mark)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(sid, *slot) for slot in slots],
            )
            written += len(slots)
    return written


def _slot(row: dict) -> tuple[str, int, int, str]:
    """A phish.net setlist row as stored: (set_number, position, song_id, trans_mark)."""
    return (
        # phish.net uses lowercase 'e' for encore; the schema CHECK constraint
        # requires uppercase 'E'. Normalize here so the rest of the codebase
        # can assume upper-case.
        str(row["set"]).upper(),
        int(row["position"]),
        int(row["songid"]),
        row.get("trans_mark") or ",",
    )


def _stored_slots(conn: sqlite3.Connection, show_id: int) -> set[tuple[str, int, int, str]]:
    return {
        (r[0], r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT set_number, position, song_id, trans_mark FROM setlist_songs "
            "WHERE show_id = ?",
            (show_id,),
        )
    }
