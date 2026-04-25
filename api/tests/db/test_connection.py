import sqlite3
from pathlib import Path
from unittest.mock import patch

from phishpicker.db.connection import apply_schema, open_db


def test_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()

    assert {"songs", "venues", "tours", "shows", "setlist_songs", "schema_meta"} <= tables


def test_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)
    apply_schema(conn)  # second apply must not raise
    conn.close()


def test_apply_schema_enables_wal(tmp_path: Path) -> None:
    """apply_schema must put the DB into WAL mode so per-request open_db
    calls don't have to verify (and can't fail under sync-poller contention)."""
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)
    conn.close()

    # Re-open and confirm the persistent journal_mode is wal.
    probe = sqlite3.connect(db_path)
    mode = probe.execute("PRAGMA journal_mode").fetchone()[0]
    probe.close()
    assert mode == "wal"


def test_open_db_does_not_query_journal_mode(tmp_path: Path) -> None:
    """Regression: PRAGMA journal_mode on every per-request open_db blocks
    under sync-poller write contention (sqlite3.OperationalError: database
    is locked at connection.py:35). WAL is persistent — the read is
    redundant. open_db must only configure busy_timeout + foreign_keys."""
    db_path = tmp_path / "test.db"
    # Pre-initialize so apply_schema's own PRAGMAs aren't observed here.
    init = open_db(db_path)
    apply_schema(init)
    init.close()

    seen: list[str] = []
    real_connect = sqlite3.connect

    def wrap_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        c = real_connect(*args, **kwargs)
        c.set_trace_callback(seen.append)
        return c

    with patch("phishpicker.db.connection.sqlite3.connect", wrap_connect):
        conn = open_db(db_path)
        conn.close()

    journal_stmts = [s for s in seen if "journal_mode" in s.lower()]
    assert journal_stmts == [], f"open_db must not touch journal_mode; saw: {journal_stmts}"
