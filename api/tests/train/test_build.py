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
