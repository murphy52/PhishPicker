from pathlib import Path

import pytest

from phishpicker.db.connection import open_db, apply_schema


def test_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert {"songs", "venues", "tours", "shows", "setlist_songs", "schema_meta"} <= tables


def test_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)
    apply_schema(conn)  # second apply must not raise
    conn.close()
