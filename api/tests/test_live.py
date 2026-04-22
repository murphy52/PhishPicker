from phishpicker.live import append_song, create_live_show, replace_song_at


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


def test_replace_song_at_updates_in_place(live_conn, seeded_live_show):
    sid = seeded_live_show
    append_song(live_conn, sid, song_id=1, set_number="1")
    append_song(live_conn, sid, song_id=2, set_number="1")
    append_song(live_conn, sid, song_id=3, set_number="1")
    ok = replace_song_at(
        live_conn,
        sid,
        entered_order=2,
        new_song_id=99,
        source="phishnet",
        superseded_by=2,
    )
    assert ok is True
    rows = live_conn.execute(
        "SELECT song_id, source, superseded_by FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (sid,),
    ).fetchall()
    assert rows[1]["song_id"] == 99
    assert rows[1]["source"] == "phishnet"
    assert rows[1]["superseded_by"] == 2


def test_replace_song_at_returns_false_when_no_match(
    live_conn, seeded_live_show
):
    ok = replace_song_at(
        live_conn,
        seeded_live_show,
        entered_order=999,
        new_song_id=42,
    )
    assert ok is False
