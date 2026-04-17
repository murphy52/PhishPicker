import json
from pathlib import Path

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.songs import upsert_songs


def test_upsert_songs_inserts_new(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]
    n = upsert_songs(conn, data)
    assert n == 2
    rows = conn.execute(
        "SELECT song_id, name, original_artist FROM songs ORDER BY song_id"
    ).fetchall()
    assert rows[0]["song_id"] == 100
    assert rows[0]["name"] == "Chalk Dust Torture"


def test_upsert_songs_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]
    upsert_songs(conn, data)
    first_seen = conn.execute("SELECT first_seen_at FROM songs ORDER BY song_id").fetchall()
    upsert_songs(conn, data)
    n = conn.execute("SELECT count(*) FROM songs").fetchone()[0]
    assert n == 2
    second_seen = conn.execute("SELECT first_seen_at FROM songs ORDER BY song_id").fetchall()
    assert first_seen == second_seen
