import json
from pathlib import Path

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.venues import upsert_venues


def test_upsert_venues_inserts_new(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"]
    n = upsert_venues(conn, data)
    assert n == 1
    rows = conn.execute(
        "SELECT venue_id, name, city, state, country FROM venues ORDER BY venue_id"
    ).fetchall()
    assert rows[0]["venue_id"] == 500
    assert rows[0]["name"] == "Madison Square Garden"


def test_upsert_venues_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"]
    upsert_venues(conn, data)
    upsert_venues(conn, data)
    n = conn.execute("SELECT count(*) FROM venues").fetchone()[0]
    assert n == 1
