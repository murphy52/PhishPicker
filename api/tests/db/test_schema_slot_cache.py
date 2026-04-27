import sqlite3

import pytest

from phishpicker.db.connection import apply_schema, open_db


def test_slot_predictions_cache_table_exists(tmp_path):
    c = open_db(tmp_path / "schema.db")
    apply_schema(c)
    cols = c.execute("PRAGMA table_info(slot_predictions_cache)").fetchall()
    names = {r["name"] for r in cols}
    assert names == {
        "show_id",
        "model_sha",
        "slot_idx",
        "actual_song_id",
        "actual_rank",
        "computed_at",
    }


def test_slot_predictions_cache_unique_per_show_model_slot(tmp_path):
    """Two inserts with the same (show_id, model_sha, slot_idx) must collide."""
    c = open_db(tmp_path / "pk.db")
    apply_schema(c)
    # Need a real shows row + songs row because of FK references.
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (100, 'X', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'V');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at)
        VALUES (1, '2026-04-25', 10, '2026-04-26');
        """
    )
    c.execute(
        "INSERT INTO slot_predictions_cache "
        "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
        "VALUES (1, 'sha', 1, 100, 7, '2026-04-26T00:00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO slot_predictions_cache "
            "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
            "VALUES (1, 'sha', 1, 100, 99, '2026-04-26T00:00:00')"
        )
