import sqlite3
import uuid
from datetime import UTC, datetime


def create_live_show(conn: sqlite3.Connection, show_date: str, venue_id: int | None) -> str:
    show_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO live_show (show_id, show_date, venue_id, started_at) VALUES (?, ?, ?, ?)",
        (show_id, show_date, venue_id, now),
    )
    conn.commit()
    return show_id


def get_live_show(conn: sqlite3.Connection, show_id: str) -> dict | None:
    row = conn.execute(
        "SELECT show_id, show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if not row:
        return None
    songs = conn.execute(
        "SELECT entered_order, song_id, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (show_id,),
    ).fetchall()
    return {
        "show_id": row["show_id"],
        "show_date": row["show_date"],
        "venue_id": row["venue_id"],
        "current_set": row["current_set"],
        "songs": [dict(s) for s in songs],
    }


def append_song(
    conn: sqlite3.Connection,
    show_id: str,
    song_id: int,
    set_number: str,
    trans_mark: str = ",",
) -> int:
    now = datetime.now(UTC).isoformat()
    next_order = (
        conn.execute(
            "SELECT COALESCE(MAX(entered_order), 0) + 1 FROM live_songs WHERE show_id = ?",
            (show_id,),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO live_songs (show_id, entered_order, song_id, set_number, trans_mark, entered_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (show_id, next_order, song_id, set_number, trans_mark, now),
    )
    conn.commit()
    return next_order


def delete_last_song(conn: sqlite3.Connection, show_id: str) -> bool:
    last = conn.execute(
        "SELECT entered_order FROM live_songs WHERE show_id = ? ORDER BY entered_order DESC LIMIT 1",
        (show_id,),
    ).fetchone()
    if not last:
        return False
    conn.execute(
        "DELETE FROM live_songs WHERE show_id = ? AND entered_order = ?",
        (show_id, last["entered_order"]),
    )
    conn.commit()
    return True


def advance_set(conn: sqlite3.Connection, show_id: str, set_number: str) -> bool:
    result = conn.execute(
        "UPDATE live_show SET current_set = ? WHERE show_id = ?",
        (set_number, show_id),
    )
    conn.commit()
    return result.rowcount > 0
