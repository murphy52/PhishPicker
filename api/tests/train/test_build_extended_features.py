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
    bustout_score caps at 1.0 when shows_since_last >= the threshold
    (currently 100 — tuned up from 50 after the Oblivion analysis showed
    that 5-show gaps were being called 'mild bustout' when they're really
    core rotation territory for Phish)."""
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


def test_segue_mark_in_populated(conn):
    """prev_trans_mark translates to segue_mark_in: ','=0, '>'=1, '->'=2."""
    rows_comma = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2],
        prev_trans_mark=",",
    )
    assert rows_comma[0].segue_mark_in == 0

    rows_seg = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2],
        prev_trans_mark=">",
    )
    assert rows_seg[0].segue_mark_in == 1

    rows_tight = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2],
        prev_trans_mark="->",
    )
    assert rows_tight[0].segue_mark_in == 2


def test_times_this_tour_scoped_to_tour(conn):
    """Chalk Dust played in show 1001 (tour 10) and 1003 (tour 10). When we
    ask from inside tour 10 (via show_id=1002 which is tour 10), we should see
    1 prior play in this tour (show 1001; 1003 is same tour but after 1002 =
    not prior)."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-02",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
        show_id=1002,  # in tour 10
    )
    # Only show 1001 (tour 10, before 2023-10-02) plays Chalk Dust.
    assert rows[0].times_this_tour == 1


def test_shows_since_last_played_this_tour_counts_tour_shows(conn):
    """Shows-since is within-tour only. Chalk Dust played in 1001 on
    2023-10-01. In show 1002 (2023-10-02, same tour), 0 tour-shows between."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-02",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
        show_id=1002,
    )
    # 1001 is the last play; no tour shows strictly between 2023-10-01 and
    # 2023-10-02 (neither endpoint).
    assert rows[0].shows_since_last_played_this_tour == 0


def test_shows_since_last_set1_opener(conn):
    """Chalk Dust opened set 1 in show 1001 (2023-10-01) and 1003 (2023-11-15).
    By cutoff 2024-07-01 the last time it opened was 2023-11-15. Count
    intervening shows (1004 on 2024-06-01) → 1."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    # Exactly one show (1004) strictly after 1003 and strictly before 2024-07-01.
    assert rows[0].shows_since_last_set1_opener == 1


def test_shows_since_last_any_opener_role_includes_set2_opener(conn):
    """Tweezer opened set 2 in show 1002 (2023-10-02). That's its only
    opener-role appearance. By cutoff 2024-07-01: 2 intervening shows
    (1003, 1004).

    NOTE: Show 1004 has Tweezer as the SOLE set-1 row (pos=5 but also the
    min-position of its set since it's the only entry), so under our
    definition of opener-role=position-is-min-of-set, Tweezer counts as
    1004's set-1 opener. Its last opener-role is 2024-06-01 → 0 intervening
    shows before 2024-07-01."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[2],
    )
    assert rows[0].shows_since_last_any_opener_role == 0


def test_avg_set_position_when_played_low_for_opener_song(conn):
    """Chalk Dust plays at positions 1, 2, 1 (per our fixture). AVG = 4/3."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].avg_set_position_when_played == pytest.approx(4 / 3)


def test_run_length_total_counts_all_shows_in_run(conn):
    """Show 1002 is part of a 2-show MSG run (1001-1002). run_length_total=2."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-02",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
        show_id=1002,
    )
    assert rows[0].run_length_total == 2
    # position 2 of 2 → 0% remaining
    assert rows[0].frac_run_remaining == pytest.approx(0.0)


def test_run_length_for_live_show_appended_to_existing_run(conn):
    """Live show on 2023-10-03 at MSG — gap=1 day from 1002 → same run.
    Run should be 1001, 1002, then our live 2023-10-03 = length 3."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-03",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_length_total == 3
    assert rows[0].run_position == 3
    assert rows[0].frac_run_remaining == pytest.approx(0.0)


def test_run_gap_of_2_days_is_still_same_run(conn):
    """Relaxed _find_run_start: 1 off-night between adjacent shows still
    counts as one run. Live show 2023-10-04 (gap of 2 days from 1002)
    should still see 1001 + 1002 + itself = 3."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-04",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_length_total == 3
    assert rows[0].run_position == 3


def test_run_gap_of_3_days_breaks_the_run(conn):
    """A 3-day gap is beyond the relaxed threshold; the live show starts a
    new run (run_length=1)."""
    rows = build_feature_rows(
        conn,
        show_date="2023-10-05",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_length_total == 1
    assert rows[0].run_position == 1


def test_days_since_debut_populated(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert abs(rows[0].days_since_debut - 12022) <= 2


def test_plays_last_6mo_counts_recent_only(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-02-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].plays_last_6mo == 3


def test_recent_play_acceleration_flags_hot_songs(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-02-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].recent_play_acceleration == 2.0


def test_is_from_latest_album_flag(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].is_from_latest_album == 0
    assert by_id[2].is_from_latest_album == 0


def test_days_since_last_new_album_is_populated(conn):
    """For 2024-07-01, the latest Phish studio album BEFORE that date is
    Sigma Oasis (2020-04-02). Evolve (2024-07-12) is after. Gap ~1551 days."""
    rows = build_feature_rows(
        conn,
        show_date="2024-07-01",
        venue_id=100,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert 1500 <= rows[0].days_since_last_new_album <= 1600
