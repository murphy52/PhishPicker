import sqlite3

from phishpicker.db.connection import apply_live_schema, apply_schema


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_songs_has_is_bustout_placeholder():
    conn = sqlite3.connect(":memory:")
    apply_schema(conn)
    assert "is_bustout_placeholder" in _cols(conn, "songs")


def test_live_songs_has_source_and_superseded_by():
    conn = sqlite3.connect(":memory:")
    apply_live_schema(conn)
    cols = _cols(conn, "live_songs")
    assert "source" in cols
    assert "superseded_by" in cols


def test_live_show_meta_table_exists():
    conn = sqlite3.connect(":memory:")
    apply_live_schema(conn)
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    ]
    assert "live_show_meta" in tables
    cols = _cols(conn, "live_show_meta")
    for c in [
        "show_id",
        "sync_enabled",
        "last_updated",
        "last_error",
        "set1_size",
        "set2_size",
        "encore_size",
    ]:
        assert c in cols
