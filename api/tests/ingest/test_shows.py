import json
from pathlib import Path

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show


def test_upsert_show_inserts_new(tmp_path: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.execute("INSERT INTO tours (tour_id, name) VALUES (77, 'Summer 2024')")
    conn.commit()
    upsert_show(conn, {"showid": 1234567, "showdate": "2024-07-21", "venueid": 500, "tourid": 77})
    row = conn.execute(
        "SELECT show_id, show_date, venue_id, tour_id FROM shows WHERE show_id = 1234567"
    ).fetchone()
    assert row is not None
    assert row["show_date"] == "2024-07-21"
    assert row["venue_id"] == 500
    assert row["tour_id"] == 77


def test_upsert_show_is_idempotent(tmp_path: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.execute("INSERT INTO tours (tour_id, name) VALUES (77, 'Summer 2024')")
    conn.commit()
    show = {"showid": 1234567, "showdate": "2024-07-21", "venueid": 500, "tourid": 77}
    upsert_show(conn, show)
    upsert_show(conn, show)
    n = conn.execute("SELECT count(*) FROM shows WHERE show_id = 1234567").fetchone()[0]
    assert n == 1


def test_upsert_setlist_songs_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    # Seed required FK rows
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.execute("INSERT INTO tours (tour_id, name) VALUES (77, 'Summer 2024')")
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at) VALUES (100, 'Chalk Dust Torture', '2024-01-01')"
    )
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at) VALUES (101, 'Tweezer', '2024-01-01')"
    )
    conn.commit()
    upsert_show(conn, {"showid": 1234567, "showdate": "2024-07-21", "venueid": 500, "tourid": 77})

    setlist_data = json.loads((fixtures_dir / "phishnet_setlist_show1234567.json").read_text())[
        "data"
    ]
    upsert_setlist_songs(conn, setlist_data)
    upsert_setlist_songs(conn, setlist_data)

    rows = conn.execute(
        "SELECT position, trans_mark FROM setlist_songs WHERE show_id = 1234567 ORDER BY position"
    ).fetchall()
    assert len(rows) == 2
    # position 2 has trans_mark ">"
    assert rows[1]["trans_mark"] == ">"


def test_upsert_setlist_dedupes_duplicate_slots(tmp_path: Path):
    """phish.net occasionally ships two rows for the same (show, set, position)
    on old ambiguous shows. We keep the last entry rather than let the
    UNIQUE constraint abort the whole ingest."""
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2024-01-01')")
    conn.execute("INSERT INTO songs (song_id, name, first_seen_at) VALUES (2, 'B', '2024-01-01')")
    conn.commit()
    upsert_show(conn, {"showid": 555, "showdate": "1989-01-01", "venueid": None, "tourid": None})
    upsert_setlist_songs(
        conn,
        [
            {"showid": 555, "set": "1", "position": 1, "songid": 1, "song": "A", "trans_mark": ","},
            {"showid": 555, "set": "1", "position": 1, "songid": 2, "song": "B", "trans_mark": ">"},
        ],
    )
    rows = conn.execute(
        "SELECT song_id, trans_mark FROM setlist_songs WHERE show_id = 555"
    ).fetchall()
    assert len(rows) == 1
    # Last one wins.
    assert rows[0]["song_id"] == 2


def test_upsert_setlist_stubs_missing_songs(tmp_path: Path):
    """phish.net's songs.json isn't exhaustive — setlists can reference a
    songid that never appeared in the songs dump. Must auto-stub."""
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    upsert_show(conn, {"showid": 777, "showdate": "2024-01-01", "venueid": None, "tourid": None})
    # song_id 999 is NOT in songs table yet.
    upsert_setlist_songs(
        conn,
        [
            {
                "showid": 777,
                "set": "1",
                "position": 1,
                "songid": 999,
                "song": "Ghost",
                "trans_mark": ",",
            }
        ],
    )
    row = conn.execute("SELECT name FROM songs WHERE song_id = 999").fetchone()
    assert row["name"] == "Ghost"


def test_upsert_setlist_normalizes_encore_to_uppercase(tmp_path: Path):
    """phish.net returns 'e' for encore but the schema CHECK requires 'E'."""
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at) VALUES (200, 'Slave', '2024-01-01')"
    )
    conn.commit()
    upsert_show(conn, {"showid": 999, "showdate": "2024-01-01", "venueid": None, "tourid": None})
    upsert_setlist_songs(
        conn,
        [{"showid": 999, "set": "e", "position": 1, "songid": 200, "trans_mark": ","}],
    )
    row = conn.execute("SELECT set_number FROM setlist_songs WHERE show_id = 999").fetchone()
    assert row["set_number"] == "E"
