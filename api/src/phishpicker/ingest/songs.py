import sqlite3
from datetime import UTC, datetime


def upsert_songs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now(UTC).isoformat()
    count = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO songs (song_id, name, original_artist, debut_date, first_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(song_id) DO UPDATE SET
                name = excluded.name,
                original_artist = excluded.original_artist,
                debut_date = excluded.debut_date
            """,
            (r["songid"], r["song"], r.get("artist"), r.get("debut"), now),
        )
        count += 1
    conn.commit()
    return count
