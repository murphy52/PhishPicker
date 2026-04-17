import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.dataset import iter_training_groups


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ds.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        INSERT INTO shows (show_id, show_date, fetched_at) VALUES
            (10, '2024-01-01', '2024-01-02'),
            (11, '2024-02-01', '2024-02-02');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (10, '1', 1, 1), (10, '1', 2, 2), (10, '1', 3, 3),
            (11, '1', 1, 4), (11, '1', 2, 5);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_generator_yields_one_group_per_slot(conn):
    groups = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=0)
    )
    # 3 slots in show 10 + 2 slots in show 11 = 5 groups.
    assert len(groups) == 5


def test_each_group_has_positive_plus_n_negatives(conn):
    groups = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=0)
    )
    for g in groups:
        assert g.positive_song_id is not None
        assert len(g.negative_song_ids) == 2
        assert g.positive_song_id not in g.negative_song_ids


def test_negatives_exclude_already_played_songs(conn):
    groups = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=10, seed=0)
    )
    # Find the 3rd slot in show 10 — played A,B before it; C is the positive.
    g = next(g for g in groups if g.show_id == 10 and g.slot_number == 3)
    assert 1 not in g.negative_song_ids
    assert 2 not in g.negative_song_ids


def test_groups_respect_cutoff(conn):
    groups = list(
        iter_training_groups(conn, cutoff_date="2024-01-15", negatives_per_positive=2, seed=0)
    )
    assert all(g.show_id == 10 for g in groups)


def test_groups_are_reproducible_with_seed(conn):
    a = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=42)
    )
    b = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=2, seed=42)
    )
    assert [g.negative_song_ids for g in a] == [g.negative_song_ids for g in b]


def test_played_before_slot_accumulates(conn):
    groups = list(
        iter_training_groups(conn, cutoff_date="2024-12-31", negatives_per_positive=1, seed=0)
    )
    s10 = [g for g in groups if g.show_id == 10]
    assert s10[0].played_before_slot == ()
    assert s10[1].played_before_slot == (1,)
    assert s10[2].played_before_slot == (1, 2)


def test_stratified_sampling_total_matches_sum(conn):
    # 1 frequency-weighted + 1 uniform = 2 negatives per positive.
    groups = list(
        iter_training_groups(
            conn,
            cutoff_date="2024-12-31",
            freq_negatives=1,
            uniform_negatives=1,
            seed=0,
        )
    )
    for g in groups:
        assert len(g.negative_song_ids) == 2


def test_stratified_sampling_prefers_frequent_songs_in_freq_pool(conn):
    # Rig the history: song 1 is played frequently, song 5 never.
    # With a large freq_negatives budget and no uniform, song 1 should always
    # dominate the sample.
    for i in range(50):
        show_id = 1000 + i
        conn.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
            (show_id, f"2023-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}", "2023-01-01"),
        )
        conn.execute(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (?, '1', 1, 1)",
            (show_id,),
        )
    conn.commit()
    # Sample many runs — aggregate counts. Song 1 (seen 50x) should appear far
    # more in the freq-weighted pool than song 5 (seen 0x).
    song1_count = 0
    song5_count = 0
    for seed in range(30):
        groups = list(
            iter_training_groups(
                conn,
                cutoff_date="2024-12-31",
                freq_negatives=1,
                uniform_negatives=0,
                seed=seed,
            )
        )
        for g in groups:
            if g.positive_song_id == 1:
                continue  # skip slots where song 1 is the positive
            if 1 in g.negative_song_ids:
                song1_count += 1
            if 5 in g.negative_song_ids:
                song5_count += 1
    assert song1_count > song5_count


def test_stratified_uniform_only_zero_negatives_ok(conn):
    groups = list(
        iter_training_groups(
            conn,
            cutoff_date="2024-12-31",
            freq_negatives=0,
            uniform_negatives=2,
            seed=0,
        )
    )
    for g in groups:
        assert len(g.negative_song_ids) == 2
