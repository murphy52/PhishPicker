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


def test_rollover_flips_at_6am_edt():
    """10h lag => the flip lands at 10:00 UTC = 06:00 EDT."""
    # 09:59 UTC = 05:59 EDT — still "yesterday", last night's show is current.
    assert rollover_today(datetime(2026, 4, 26, 9, 59, tzinfo=UTC)) == "2026-04-25"
    # 10:00 UTC = 06:00 EDT — flipped.
    assert rollover_today(datetime(2026, 4, 26, 10, 0, tzinfo=UTC)) == "2026-04-26"


def test_rollover_does_not_flip_while_a_west_coast_show_is_still_on():
    """The binding constraint on going earlier: a west-coast show ends ~23:30 PT
    = 02:30 ET. Flip before that and /upcoming jumps off a show still in progress.
    06:30 UTC = 02:30 ET on the 26th must still read as the 25th."""
    assert rollover_today(datetime(2026, 4, 26, 6, 30, tzinfo=UTC)) == "2026-04-25"


def test_rollover_lag_stays_within_the_safe_band():
    """Guard the constant: below ~8h it clips west-coast shows mid-set; above 15h
    you're back to not seeing the next show until midday."""
    from phishpicker.last_show import ROLLOVER_LAG_HOURS

    assert 8 <= ROLLOVER_LAG_HOURS <= 15
