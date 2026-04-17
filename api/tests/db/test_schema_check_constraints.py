import sqlite3
from pathlib import Path

import pytest

from phishpicker.db.connection import apply_live_schema, apply_schema, open_db


def test_setlist_songs_rejects_invalid_set_number(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "p.db")
    apply_schema(conn)
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'X', '2020-01-01')"
    )
    conn.execute(
        "INSERT INTO shows (show_id, show_date, fetched_at) "
        "VALUES (1, '2020-01-01', '2020-01-01T00:00:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (1, 'e', 1, 1)"
        )


def test_live_show_rejects_invalid_current_set(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "live.db")
    apply_live_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO live_show (show_id, show_date, started_at, current_set) "
            "VALUES ('uuid-1', '2020-01-01', '2020-01-01T00:00:00Z', 'invalid')"
        )


def test_live_songs_rejects_invalid_set_number(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "live.db")
    apply_live_schema(conn)
    conn.execute(
        "INSERT INTO live_show (show_id, show_date, started_at) "
        "VALUES ('uuid-1', '2020-01-01', '2020-01-01T00:00:00Z')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO live_songs "
            "(show_id, entered_order, song_id, set_number, entered_at) "
            "VALUES ('uuid-1', 1, 100, 'bogus', '2020-01-01T00:00:00Z')"
        )
