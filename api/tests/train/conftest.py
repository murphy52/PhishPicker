"""Training-subpackage fixtures. Small synthetic DB with a deterministic
frequency signal so a LightGBM ranker can learn something trivially from it.
"""

import pytest

from phishpicker.db.connection import apply_schema, open_db


@pytest.fixture
def small_train_db(tmp_path):
    """30 shows, 5 songs. Song 1 always opens set 1; song 2 always closes;
    songs 3/4 fill the middle; song 5 is never played.

    That's enough signal for a LambdaRank model trained for 50+ rounds to
    rank song 1 > song 5 when asked for the opener.
    """
    c = open_db(tmp_path / "train.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        """
    )
    for i in range(30):
        show_id = 100 + i
        # Spread shows across the year so ORDER BY show_date is stable.
        month = (i % 12) + 1
        day = (i % 27) + 1
        show_date = f"2024-{month:02d}-{day:02d}"
        c.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
            (show_id, show_date, show_date),
        )
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
            [
                (show_id, "1", 1, 1),
                (show_id, "1", 2, 3),
                (show_id, "1", 3, 4),
                (show_id, "1", 4, 2),
            ],
        )
    c.commit()
    try:
        yield c
    finally:
        c.close()
