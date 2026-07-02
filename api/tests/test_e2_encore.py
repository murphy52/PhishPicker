"""Double/triple encores: phish.net emits set_number 'E2'/'E3', which the
live schema must accept (a CHECK rejection crashes append_song mid-show)."""

from phishpicker.live import advance_set, append_song, create_live_show


def test_append_e2_encore_song(live_conn):
    show_id = create_live_show(live_conn, "2026-07-07", venue_id=1)
    append_song(live_conn, show_id, song_id=1, set_number="E")
    append_song(live_conn, show_id, song_id=2, set_number="E2")  # must not raise
    append_song(live_conn, show_id, song_id=3, set_number="E3")  # must not raise
    rows = live_conn.execute(
        "SELECT set_number FROM live_songs ORDER BY entered_order"
    ).fetchall()
    assert [r["set_number"] for r in rows] == ["E", "E2", "E3"]


def test_apply_live_schema_migrates_old_set_checks(tmp_path):
    """A live.db created before E2/E3 support keeps its old CHECK constraints
    (CREATE TABLE IF NOT EXISTS never rewrites them). apply_live_schema must
    rebuild those tables, preserving existing rows."""
    from phishpicker.db.connection import apply_live_schema, open_db

    conn = open_db(tmp_path / "live.db")
    conn.executescript(
        """
        CREATE TABLE live_show (
            show_id TEXT PRIMARY KEY,
            show_date TEXT NOT NULL,
            venue_id INTEGER,
            started_at TEXT NOT NULL,
            current_set TEXT NOT NULL DEFAULT '1' CHECK (current_set IN ('1','2','3','4','E')),
            reconciled_at TEXT
        );
        CREATE TABLE live_songs (
            show_id TEXT NOT NULL REFERENCES live_show(show_id) ON DELETE CASCADE,
            entered_order INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            set_number TEXT NOT NULL CHECK (set_number IN ('1','2','3','4','E')),
            trans_mark TEXT NOT NULL DEFAULT ',',
            entered_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            superseded_by INTEGER,
            PRIMARY KEY (show_id, entered_order)
        );
        INSERT INTO live_show (show_id, show_date, started_at)
            VALUES ('abc', '2026-07-07', '2026-07-07T00:00:00Z');
        INSERT INTO live_songs (show_id, entered_order, song_id, set_number, entered_at)
            VALUES ('abc', 1, 100, '1', '2026-07-07T01:00:00Z');
        """
    )
    conn.commit()

    apply_live_schema(conn)

    append_song(conn, "abc", song_id=2, set_number="E2")  # must not raise
    rows = conn.execute(
        "SELECT song_id, set_number FROM live_songs ORDER BY entered_order"
    ).fetchall()
    assert [(r["song_id"], r["set_number"]) for r in rows] == [(100, "1"), (2, "E2")]
    show = conn.execute("SELECT show_date FROM live_show WHERE show_id='abc'").fetchone()
    assert show["show_date"] == "2026-07-07"
    conn.close()


def test_advance_set_to_e2(live_conn):
    show_id = create_live_show(live_conn, "2026-07-07", venue_id=1)
    assert advance_set(live_conn, show_id, "E2")  # must not raise
    row = live_conn.execute(
        "SELECT current_set FROM live_show WHERE show_id = ?", (show_id,)
    ).fetchone()
    assert row["current_set"] == "E2"
