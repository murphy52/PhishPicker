import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.build import build_feature_rows


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "build.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, original_artist, debut_date, first_seen_at)
        VALUES
            (1, 'Tweezer', NULL, '1990-05-01', '2020-01-01'),
            (2, 'Fluffhead', NULL, '1989-01-01', '2020-01-01'),
            (3, 'Possum', NULL, '1985-01-01', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG');
        INSERT INTO shows (show_id, show_date, venue_id, tour_position, fetched_at)
        VALUES
            (10, '2024-01-01', 1, 1, '2024-01-02'),
            (11, '2024-06-01', 1, 2, '2024-06-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id, trans_mark)
        VALUES
            (10, '1', 1, 1, ','),
            (10, '1', 2, 2, '>'),
            (11, '1', 1, 3, ',');
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_build_emits_one_row_per_candidate(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 3],
    )
    assert len(rows) == 3
    assert {r.song_id for r in rows} == {1, 2, 3}


def test_build_populates_total_plays_from_history(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 3],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[1].total_plays_ever == 1
    assert by_id[2].total_plays_ever == 1
    assert by_id[3].total_plays_ever == 1


def test_build_sets_prev_song_from_played(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2, 3],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[2].prev_song_id == 1
    assert by_id[3].prev_song_id == 1


def test_build_prev_song_is_missing_when_no_played(conn):
    from phishpicker.train.features import MISSING_INT

    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].prev_song_id == MISSING_INT


def test_build_slot_number_reflects_played_count(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1, 2],
        current_set="1",
        candidate_song_ids=[3],
    )
    assert rows[0].slot_number == 3


def test_build_era_on_every_row(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2],
    )
    for r in rows:
        assert r.era == 4


def test_build_current_set_encoding(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="E",
        candidate_song_ids=[1],
    )
    assert rows[0].current_set == 4


def test_build_is_set2_flag_true_in_set2(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1],
        current_set="2",
        candidate_song_ids=[2, 3],
        prev_set_number="1",
    )
    for r in rows:
        assert r.is_set2 == 1


def test_build_is_set2_flag_false_in_set1(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].is_set2 == 0


def test_build_is_set2_flag_false_in_encore(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1],
        current_set="E",
        candidate_song_ids=[2],
        prev_set_number="2",
    )
    assert rows[0].is_set2 == 0


def test_build_is_first_in_set_true_at_show_start(conn):
    # No prior songs played, no prev_set_number — this is slot 1 of set 1.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].is_first_in_set == 1


def test_build_is_first_in_set_true_when_set_changes(conn):
    # Set 1 just ended, now starting set 2: prev_set_number differs from current_set.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1, 2],
        current_set="2",
        candidate_song_ids=[3],
        prev_set_number="1",
    )
    assert rows[0].is_first_in_set == 1


def test_build_is_first_in_set_false_mid_set(conn):
    # We're deep in set 1: prev_set_number=="1" matches current_set.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2, 3],
        prev_set_number="1",
    )
    for r in rows:
        assert r.is_first_in_set == 0


def test_build_is_first_in_set_true_at_encore_start(conn):
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1, 2, 3],
        current_set="E",
        candidate_song_ids=[1],
        prev_set_number="2",
    )
    assert rows[0].is_first_in_set == 1


def test_build_slots_into_current_set_defaults_to_one(conn):
    # No prior songs in the current set → first slot of the set.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].slots_into_current_set == 1


def test_build_slots_into_current_set_reflects_caller_value(conn):
    # Slot 6 of set 2 — caller's responsibility to track and pass through.
    # Used by the model to know we're approaching set-2-closer territory.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1, 2, 3],
        current_set="2",
        candidate_song_ids=[1, 2, 3],
        prev_set_number="2",
        slots_into_current_set=6,
    )
    for r in rows:
        assert r.slots_into_current_set == 6


def test_build_slots_into_current_set_resets_on_new_set(conn):
    # Slot 1 of set 2 (set just changed) — caller passes 1 even though
    # several songs were played overall.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1, 2],
        current_set="2",
        candidate_song_ids=[3],
        prev_set_number="1",
        slots_into_current_set=1,
    )
    assert rows[0].slots_into_current_set == 1


def test_run_saturation_pressure_zero_at_run_start(tmp_path):
    """At run_position=1 (first night of any run / one-off show), the
    expected-plays-so-far term is zero, so saturation pressure is just
    -plays_this_run_count, which is 0 since no prior nights exist."""
    from phishpicker.db.connection import apply_schema, open_db

    c = open_db(tmp_path / "sat0.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'Tweezer', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG'), (2, 'Hampton');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (10, '2024-01-01', 2, '2024-01-02'),
            (11, '2024-06-01', 2, '2024-06-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id)
        VALUES (10, '1', 1, 1), (11, '1', 1, 1);
        """
    )
    c.commit()
    rows = build_feature_rows(
        c,
        show_date="2024-12-01",
        venue_id=1,  # MSG — not used by either past show, so run_position=1
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_position == 1
    assert rows[0].run_saturation_pressure == 0.0
    c.close()


def test_run_saturation_pressure_mid_residency(tmp_path):
    """At run_position=5 with a song that's been played 1× so far in the
    run, saturation = (12mo_rate × 4) − 1. Set up: song played at 4 of 10
    past-year shows, residency of 5 consecutive same-venue shows, song
    played on 1 of the prior 4 residency nights."""
    from phishpicker.db.connection import apply_schema, open_db

    c = open_db(tmp_path / "sat_mid.db")
    apply_schema(c)
    # 10 past-year shows: 4 at residency venue (dates 06-01..06-04), 6
    # elsewhere across the year. Song A played at 4 total: 1 residency
    # night (06-01) + 3 other shows.
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG'), (2, 'Hampton');

        -- 4 nights at MSG (residency); 6 other shows at Hampton scattered.
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (101, '2024-06-01', 1, '2024-06-02'),
            (102, '2024-06-02', 1, '2024-06-03'),
            (103, '2024-06-03', 1, '2024-06-04'),
            (104, '2024-06-04', 1, '2024-06-05'),
            (201, '2024-01-15', 2, '2024-01-16'),
            (202, '2024-02-15', 2, '2024-02-16'),
            (203, '2024-03-15', 2, '2024-03-16'),
            (204, '2024-04-15', 2, '2024-04-16'),
            (205, '2024-05-15', 2, '2024-05-16'),
            (206, '2024-05-25', 2, '2024-05-26');

        -- Song A played at: residency night 101 + 3 Hampton shows.
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (101, '1', 1, 1),
            (201, '1', 1, 1),
            (202, '1', 1, 1),
            (203, '1', 1, 1);
        """
    )
    c.commit()
    # Live: 2024-06-05 at MSG. With 4 prior MSG nights all consecutive,
    # the walk-until-venue-changes finds run_position=5.
    # plays_last_12mo for song 1 = 4 (DISTINCT shows after sandwich-fix).
    # shows_last_12mo = 10. Rate = 4/10 = 0.4.
    # plays_this_run_count = 1 (song A on 06-01 within run start..show_date).
    # Expected saturation = 0.4 × (5 − 1) − 1 = 1.6 − 1 = 0.6.
    rows = build_feature_rows(
        c,
        show_date="2024-06-05",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_position == 5
    assert rows[0].plays_last_12mo == 4
    assert rows[0].plays_this_run_count == 1
    assert rows[0].run_saturation_pressure == pytest.approx(0.6)
    c.close()


def test_run_saturation_pressure_zero_when_no_prior_year_shows(tmp_path):
    """Divide-by-zero guard: if shows_last_12mo is 0 (cold start), the
    feature returns 0 instead of NaN."""
    from phishpicker.db.connection import apply_schema, open_db

    c = open_db(tmp_path / "sat_cold.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (101, '2024-06-01', 1, '2024-06-02'),
            (102, '2024-06-02', 1, '2024-06-03');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id)
        VALUES (101, '1', 1, 1);
        """
    )
    c.commit()
    # Live: 2025-07-01 — past-year window (2024-07-01..2025-07-01) excludes
    # both 2024-06 shows (just barely). shows_last_12mo = 0, even though
    # the residency walk still finds them. Guard prevents divide-by-zero.
    rows = build_feature_rows(
        c,
        show_date="2025-07-01",
        venue_id=1,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1],
    )
    assert rows[0].run_saturation_pressure == 0.0
    c.close()


def test_build_bigram_feature_populated_when_prev_known(conn):
    # After Tweezer (1), Fluffhead (2) was played once in show 10. Bigram prob
    # for 1→2 (raw) should be positive.
    rows = build_feature_rows(
        conn,
        show_date="2024-12-31",
        venue_id=1,
        played_songs=[1],
        current_set="1",
        candidate_song_ids=[2, 3],
    )
    by_id = {r.song_id: r for r in rows}
    assert by_id[2].bigram_prev_to_this > 0.0
