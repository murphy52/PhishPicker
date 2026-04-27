from datetime import UTC, datetime

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.last_show import resolve_last_show_id, rollover_today


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ls.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (100, '2026-04-23', 10, '2026-04-24'),
            (101, '2026-04-24', 10, '2026-04-25'),
            (102, '2026-04-25', 10, '2026-04-26'),
            (103, '2026-04-30', 10, '2026-04-26');  -- future, no setlist yet
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (100, '1', 1, 1),
            (101, '1', 1, 1),
            (102, '1', 1, 1);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_resolves_to_most_recent_show_with_setlist(conn):
    sid = resolve_last_show_id(conn, today="2026-04-27")
    assert sid == 102


def test_returns_none_when_no_completed_show(conn):
    sid = resolve_last_show_id(conn, today="2026-04-22")
    assert sid is None


def test_skips_shows_without_setlist_rows(conn):
    sid = resolve_last_show_id(conn, today="2026-05-01")
    assert sid == 102


def test_rollover_today_is_15_hours_lagged():
    # 2026-04-26T16:00Z minus 15h = 2026-04-26T01:00Z → date 2026-04-26.
    now = datetime(2026, 4, 26, 16, 0, tzinfo=UTC)
    assert rollover_today(now) == "2026-04-26"
    # 2026-04-26T10:00Z minus 15h = 2026-04-25T19:00Z → date 2026-04-25.
    now = datetime(2026, 4, 26, 10, 0, tzinfo=UTC)
    assert rollover_today(now) == "2026-04-25"
