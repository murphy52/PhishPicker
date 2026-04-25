import sqlite3

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.bigrams import compute_bigram_probs


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "bigrams.db"
    c = open_db(db_path)
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01');
        INSERT INTO shows (show_id, show_date, fetched_at) VALUES
            (10, '2024-01-01', '2024-01-02'),
            (11, '2024-01-02', '2024-01-03'),
            (12, '2024-06-01', '2024-06-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (10, '1', 1, 1), (10, '1', 2, 2), (10, '1', 3, 3),
            (11, '1', 1, 1), (11, '1', 2, 2),
            (12, '1', 1, 1), (12, '1', 2, 4);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_bigram_returns_probability_of_next_given_prev(conn: sqlite3.Connection):
    # Cutoff after all three shows: A→B seen twice, A→D seen once.
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    assert probs[(1, 2)] == pytest.approx(2 / 3)
    assert probs[(1, 4)] == pytest.approx(1 / 3)


def test_bigram_respects_cutoff_date(conn: sqlite3.Connection):
    # Cutoff before 2024-06-01 excludes show 12 → A→B is 1.0, A→D missing.
    probs = compute_bigram_probs(conn, cutoff_date="2024-03-01", alpha=0.0)
    assert probs[(1, 2)] == pytest.approx(1.0)
    assert (1, 4) not in probs


def test_bigram_smoothing_lowers_observed_but_keeps_key(conn: sqlite3.Connection):
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=1.0)
    # Smoothed must be strictly between 0 and the unsmoothed 2/3.
    assert 0 < probs[(1, 2)] < 2 / 3


def test_bigram_does_not_cross_set_boundaries(conn: sqlite3.Connection):
    # Add an encore; transition from set 1's last song (C) to encore's song
    # must NOT register as a bigram because of the set boundary.
    conn.execute(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (10, 'E', 1, 4)"
    )
    conn.commit()
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    assert (3, 4) not in probs


def test_bigram_does_not_cross_show_boundaries(conn: sqlite3.Connection):
    # Show 10 ends with C, show 11 starts with A. No C→A bigram.
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    assert (3, 1) not in probs


def test_bigram_collapses_sandwich_repeats(conn: sqlite3.Connection):
    # Phish sandwich: A → B → A within one set is one performance of A
    # interrupted by B, not two A plays. The sandwich-return transition
    # (B→A) is an artifact of the sandwich and must not register as a
    # real bigram.
    conn.execute(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
        "VALUES (10, '2', 1, 1), (10, '2', 2, 2), (10, '2', 3, 1)"
    )
    conn.commit()
    probs = compute_bigram_probs(conn, cutoff_date="2024-12-31", alpha=0.0)
    # B→A would have been the sandwich return — must be absent.
    assert (2, 1) not in probs
    # Without the sandwich's spurious B→A diluting B's transitions, B→C
    # (from show 10 set 1) is B's sole transition.
    assert probs[(2, 3)] == pytest.approx(1.0)
