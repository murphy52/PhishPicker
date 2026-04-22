from phishpicker.live import create_live_show


def test_create_live_show_idempotent_on_date(live_conn):
    first = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    second = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    assert first == second
    rows = live_conn.execute(
        "SELECT COUNT(*) FROM live_show WHERE show_date = ?",
        ("2026-04-23",),
    ).fetchone()[0]
    assert rows == 1


def test_create_live_show_different_dates_get_distinct_ids(live_conn):
    a = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    b = create_live_show(live_conn, "2026-04-24", venue_id=1597)
    assert a != b
