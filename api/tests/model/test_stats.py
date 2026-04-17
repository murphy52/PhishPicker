import sqlite3
from pathlib import Path

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.model.stats import compute_song_stats


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    c = open_db(db_path)
    apply_schema(c)
    return c


def _seed_venue(conn: sqlite3.Connection, venue_id: int) -> None:
    conn.execute(
        "INSERT INTO venues (venue_id, name, city, state, country) VALUES (?, ?, ?, ?, ?)",
        (venue_id, "MSG", "New York", "NY", "USA"),
    )


def _seed_tour(conn: sqlite3.Connection, tour_id: int) -> None:
    conn.execute(
        "INSERT INTO tours (tour_id, name) VALUES (?, ?)",
        (tour_id, "Summer 2024"),
    )


def _seed_song(conn: sqlite3.Connection, song_id: int) -> None:
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at) VALUES (?, ?, ?)",
        (song_id, f"Song {song_id}", "2024-01-01T00:00:00"),
    )


def _seed_show(
    conn: sqlite3.Connection,
    show_id: int,
    show_date: str,
    venue_id: int,
    tour_id: int,
) -> None:
    conn.execute(
        """INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        (show_id, show_date, venue_id, tour_id, "2024-07-23T00:00:00"),
    )


def _seed_setlist_song(
    conn: sqlite3.Connection,
    show_id: int,
    song_id: int,
    set_number: str = "1",
    position: int = 1,
) -> None:
    conn.execute(
        """INSERT INTO setlist_songs (show_id, set_number, position, song_id)
           VALUES (?, ?, ?, ?)""",
        (show_id, set_number, position, song_id),
    )


def test_compute_song_stats_live_run(conn: sqlite3.Connection) -> None:
    """Song played Jul 19 at venue 500 is in the run when computing for Jul 22
    (consecutive shows Jul 19, 20, 21 form a run; Jul 22 continues it)."""
    _seed_venue(conn, 500)
    _seed_tour(conn, 77)
    _seed_song(conn, 100)

    # Three consecutive shows at venue 500
    _seed_show(conn, 1, "2024-07-19", 500, 77)
    _seed_show(conn, 2, "2024-07-20", 500, 77)
    _seed_show(conn, 3, "2024-07-21", 500, 77)

    # Song 100 played only on Jul 19
    _seed_setlist_song(conn, 1, 100)

    conn.commit()

    stats = compute_song_stats(conn, "2024-07-22", 500, [100])

    assert stats[100].played_already_this_run is True
    # Shows between Jul 19 and Jul 22 (exclusive both ends): Jul 20, Jul 21 = 2
    assert stats[100].shows_since_last_played_anywhere == 2


def test_compute_song_stats_breaks_run_on_day_gap(conn: sqlite3.Connection) -> None:
    """A 3-day gap between Jul 19 and Jul 22 means they are NOT the same run.
    Song played Jul 19 should NOT count as played_already_this_run for Jul 22."""
    _seed_venue(conn, 500)
    _seed_tour(conn, 77)
    _seed_song(conn, 100)

    # Two shows with a gap: Jul 19 and Jul 22 (no Jul 20 or Jul 21)
    _seed_show(conn, 1, "2024-07-19", 500, 77)
    _seed_show(conn, 2, "2024-07-22", 500, 77)

    # Song 100 played on Jul 19
    _seed_setlist_song(conn, 1, 100)

    conn.commit()

    stats = compute_song_stats(conn, "2024-07-22", 500, [100])

    assert stats[100].played_already_this_run is False


def test_compute_song_stats_never_played(conn: sqlite3.Connection) -> None:
    """Song with no play history returns None for shows_since_last and 0 total plays."""
    _seed_venue(conn, 500)
    _seed_tour(conn, 77)
    _seed_song(conn, 100)

    # One show on Jul 21, no setlist entries for song 100
    _seed_show(conn, 1, "2024-07-21", 500, 77)

    conn.commit()

    stats = compute_song_stats(conn, "2024-07-22", 500, [100])

    assert stats[100].shows_since_last_played_anywhere is None
    assert stats[100].total_plays_ever == 0
    assert stats[100].played_already_this_run is False


def test_compute_song_stats_role_scores(conn: sqlite3.Connection) -> None:
    """Role scores reflect actual opener/encore/middle distribution."""
    _seed_venue(conn, 500)
    _seed_tour(conn, 77)
    _seed_song(conn, 100)

    # 4 shows: song opens show 1, encores show 2, mid-set shows 3 and 4
    for _i, (sid, d) in enumerate(
        [(1, "2024-07-18"), (2, "2024-07-19"), (3, "2024-07-20"), (4, "2024-07-21")], start=1
    ):
        _seed_show(conn, sid, d, 500, 77)
    _seed_setlist_song(conn, 1, 100, set_number="1", position=1)   # opener
    _seed_setlist_song(conn, 2, 100, set_number="E", position=1)   # encore
    _seed_setlist_song(conn, 3, 100, set_number="2", position=3)   # mid-set
    _seed_setlist_song(conn, 4, 100, set_number="2", position=5)   # mid-set
    conn.commit()

    stats = compute_song_stats(conn, "2024-07-22", 500, [100])

    import pytest
    assert stats[100].opener_score == pytest.approx(1 / 4)
    assert stats[100].encore_score == pytest.approx(1 / 4)
    assert stats[100].middle_score == pytest.approx(2 / 4)
