import json
from pathlib import Path

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.derive import recompute_run_and_tour_positions
from phishpicker.ingest.shows import upsert_show


def test_run_position_for_msg_run(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.execute("INSERT INTO tours (tour_id, name) VALUES (77, 'NYE 2024')")
    conn.commit()

    shows = json.loads((fixtures_dir / "phishnet_run_at_msg.json").read_text())["data"]
    for show in shows:
        upsert_show(conn, show)

    recompute_run_and_tour_positions(conn)

    rows = conn.execute(
        "SELECT show_id, run_position, run_length FROM shows ORDER BY show_date, show_id"
    ).fetchall()
    assert len(rows) == 4
    for i, row in enumerate(rows, start=1):
        assert row["run_position"] == i
        assert row["run_length"] == 4


def test_null_venue_shows_do_not_group_into_run(tmp_path: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    upsert_show(conn, {"showid": 5000001, "showdate": "2024-08-01", "venueid": None, "tourid": None})
    upsert_show(conn, {"showid": 5000002, "showdate": "2024-08-02", "venueid": None, "tourid": None})
    recompute_run_and_tour_positions(conn)
    rows = conn.execute(
        "SELECT run_position, run_length FROM shows ORDER BY show_date, show_id"
    ).fetchall()
    for row in rows:
        assert row["run_position"] == 1
        assert row["run_length"] == 1


def test_run_resets_on_non_consecutive_dates(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.commit()

    upsert_show(conn, {"showid": 3000001, "showdate": "2024-01-01", "venueid": 500, "tourid": None})
    upsert_show(conn, {"showid": 3000002, "showdate": "2024-01-31", "venueid": 500, "tourid": None})

    recompute_run_and_tour_positions(conn)

    rows = conn.execute(
        "SELECT show_id, run_position, run_length FROM shows ORDER BY show_date, show_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["run_position"] == 1
    assert rows[0]["run_length"] == 1
    assert rows[1]["run_position"] == 1
    assert rows[1]["run_length"] == 1


def test_tour_position_increments(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (500, 'Madison Square Garden')")
    conn.execute("INSERT INTO venues (venue_id, name) VALUES (501, 'Another Venue')")
    conn.execute("INSERT INTO tours (tour_id, name) VALUES (99, 'Summer Tour')")
    conn.commit()

    upsert_show(conn, {"showid": 4000001, "showdate": "2024-06-01", "venueid": 500, "tourid": 99})
    upsert_show(conn, {"showid": 4000002, "showdate": "2024-06-05", "venueid": 501, "tourid": 99})

    recompute_run_and_tour_positions(conn)

    rows = conn.execute(
        "SELECT show_id, tour_position FROM shows ORDER BY show_date, show_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["tour_position"] == 1
    assert rows[1]["tour_position"] == 2
