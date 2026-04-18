"""Test-first coverage for the second batch of features.

Baseline audit: verify that features that SHOULD be populated from the DB
actually have non-sentinel values when the DB has the data. Catches silent
regressions where a field gets declared in FeatureRow but never filled.
"""

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.build import build_feature_rows


@pytest.fixture
def conn(tmp_path):
    """Build a rich mini-DB that exercises every new feature."""
    c = open_db(tmp_path / "ext.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, original_artist, debut_date, first_seen_at) VALUES
            (1, 'Chalk Dust Torture', NULL,      '1991-08-02', '2020-01-01'),
            (2, 'Tweezer',             NULL,     '1990-04-07', '2020-01-01'),
            (3, 'Fluffhead',           NULL,     '1988-08-06', '2020-01-01'),
            (4, 'Loving Cup',        'Rolling Stones', '1997-07-25', '2020-01-01'),
            (5, 'Simple',              NULL,     '1994-05-04', '2020-01-01'),
            (6, 'NEVER PLAYED',        NULL,     NULL,         '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (100, 'MSG'), (101, 'Hampton');
        INSERT INTO tours (tour_id, name, start_date, end_date) VALUES
            (10, 'Fall 2023', '2023-10-01', '2023-12-31');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, run_position, run_length, tour_position, fetched_at) VALUES
            (1001, '2023-10-01', 100, 10, 1, 2, 1, '2023-10-02'),
            (1002, '2023-10-02', 100, 10, 2, 2, 2, '2023-10-03'),
            (1003, '2023-11-15', 101, 10, 1, 1, 10, '2023-11-16'),
            (1004, '2024-06-01', 100, NULL, 1, 1, 1, '2024-06-02');
        -- show 1001 MSG: opens w/ Chalk Dust in set 1, closes set 1 with Tweezer,
        --                set 2 is Fluffhead > Loving Cup, encore is Simple.
        INSERT INTO setlist_songs (show_id, set_number, position, song_id, trans_mark) VALUES
            (1001, '1', 1, 1, ','),
            (1001, '1', 2, 2, ','),     -- Tweezer closes set 1
            (1001, '2', 1, 3, '>'),
            (1001, '2', 2, 4, ','),
            (1001, 'E', 1, 5, ','),
        -- show 1002 MSG: opens set 2 with Tweezer. Chalk Dust mid-set-1.
            (1002, '1', 1, 5, ','),
            (1002, '1', 2, 1, ','),
            (1002, '2', 1, 2, ','),     -- Tweezer opens set 2
            (1002, '2', 2, 3, ','),
        -- show 1003 Hampton, before our cutoff, Chalk Dust played.
            (1003, '1', 1, 1, ','),
        -- show 1004 MSG, Tweezer again.
            (1004, '1', 5, 2, ',');
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_set1_opener_rate_populated(conn):
    """Chalk Dust opened set 1 in shows 1001 and 1003 (2 of 3 appearances)."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 5],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].set1_opener_rate == pytest.approx(2 / 3)
    # Simple opened set 1 once out of 2 appearances (show 1002).
    assert by_id[5].set1_opener_rate == pytest.approx(1 / 2)


def test_set2_opener_rate_distinct_from_set1(conn):
    """Tweezer opened set 2 in show 1002 (1 of 3 total plays)."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2],
    )
    assert rows[0].set2_opener_rate == pytest.approx(1 / 3)
    assert rows[0].set1_opener_rate == 0.0


def test_closer_score_populated(conn):
    """Tweezer closed set 1 in shows 1001 (pos 2 is last) and 1004 (pos 5 is
    last). Not a closer in 1002 (pos 1 in a 2-song set 2). 2 of 3 plays."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2],
    )
    assert rows[0].closer_score == pytest.approx(2 / 3)


def test_encore_rate_populated(conn):
    """Simple was the encore in 1001. 1 encore out of 2 plays."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[5],
    )
    assert rows[0].encore_rate == pytest.approx(1 / 2)


def test_times_at_venue_counts_prior_plays_at_venue(conn):
    """Tweezer played at MSG in shows 1001, 1002, 1004 — all MSG."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2],
    )
    assert rows[0].times_at_venue == 3


def test_times_at_venue_is_zero_when_never_here(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=101,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2],  # Tweezer never at Hampton
    )
    assert rows[0].times_at_venue == 0


def test_venue_debut_affinity_is_plays_at_venue_over_total(conn):
    """Tweezer: 3 MSG plays / 3 total = 1.0."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2, 1],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[2].venue_debut_affinity == pytest.approx(1.0)
    # Chalk Dust: 2 MSG plays (1001, 1002) / 3 total = 2/3.
    assert by_id[1].venue_debut_affinity == pytest.approx(2 / 3)


def test_debut_year_populated_from_songs_table(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 3, 4, 6],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].debut_year == 1991
    assert by_id[2].debut_year == 1990
    assert by_id[3].debut_year == 1988
    assert by_id[4].debut_year == 1997
    # Song with null debut_date keeps the MISSING_INT sentinel.
    from phishpicker.train.features import MISSING_INT

    assert by_id[6].debut_year == MISSING_INT


def test_is_cover_populated_from_original_artist(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[4, 1],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[4].is_cover == 1  # Loving Cup -> Rolling Stones cover
    assert by_id[1].is_cover == 0


def test_bustout_score_flags_long_gap(conn):
    """A song that hasn't been played in many shows gets a high bustout score.
    Chalk Dust last played in show 1003 (2023-11-15); by our cutoff 2024-07-01,
    there's 1 intervening show (1004 on 2024-06-01). Not a bustout.
    We'll define bustout_score as 1.0 if shows_since_last >= 50, else ratio."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 3],
    )
    by_id = {r.song_id: r for r in rows}
    # Chalk Dust: small gap → low bustout
    assert by_id[1].bustout_score < 0.1
    # Fluffhead: last played 2023-10-01 / 1002, gap is bigger → higher bustout
    assert by_id[3].bustout_score > by_id[1].bustout_score


def test_days_since_last_played_anywhere_populated(conn):
    """Chalk Dust last played 2023-11-15. From 2024-07-01 that's 229 days."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 6],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].days_since_last_played_anywhere == 229
    # Song never played keeps sentinel.
    from phishpicker.train.features import MISSING_INT

    assert by_id[6].days_since_last_played_anywhere == MISSING_INT


def test_tour_opener_rate_populated(conn):
    """Tour-opener = show where tour_position=1. Show 1001 is the tour
    opener; both Chalk Dust and Tweezer played there. Each has 1 tour-opener
    of 3 plays."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].tour_opener_rate == pytest.approx(1 / 3)
    assert by_id[2].tour_opener_rate == pytest.approx(1 / 3)


def test_tour_closer_rate_populated(conn):
    """Show 1003 is tour_position=10, the max for tour_id=10 in this fixture
    (our fixture has tour_positions 1, 2, 10). Chalk Dust played there →
    1 tour-closer of 3 plays."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].tour_closer_rate == pytest.approx(1 / 3)


def test_run_position_pulled_from_shows_row(conn):
    """show 1002 is position 2 of a 2-show MSG run."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-02",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
        show_id=1002,
    )
    assert rows[0].run_position == 2
