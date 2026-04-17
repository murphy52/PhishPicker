from pathlib import Path

from phishpicker.db.connection import apply_live_schema, open_db


def test_live_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    conn = open_db(db_path)
    apply_live_schema(conn)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert {"live_show", "live_songs"} <= tables
