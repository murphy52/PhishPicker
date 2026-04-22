import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def live_conn(tmp_path):
    """In-memory-like live DB on tmp_path; schema applied."""
    from phishpicker.db.connection import apply_live_schema, open_db

    conn = open_db(tmp_path / "live.db")
    apply_live_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def seeded_client(tmp_path, monkeypatch, fixtures_dir) -> Iterator[TestClient]:
    """Fresh DB + live DB, seeded with a small deterministic set of shows/songs,
    wrapped in a TestClient that fires the FastAPI lifespan (`with ... as client`).
    Reused by Tasks 13, 14."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test-key")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    # Seed both DBs before the app loads them.
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
    from phishpicker.ingest.derive import recompute_run_and_tour_positions
    from phishpicker.ingest.pipeline import upsert_tour_stubs
    from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show
    from phishpicker.ingest.songs import upsert_songs
    from phishpicker.ingest.venues import upsert_venues

    db = open_db(tmp_path / "phishpicker.db")
    apply_schema(db)
    live = open_db(tmp_path / "live.db")
    apply_live_schema(live)

    # Small fixture: Chalk Dust (100), Tweezer (101), MSG (500), one 2024-07-21 show.
    upsert_songs(db, json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"])
    upsert_venues(
        db, json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"]
    )
    shows_data = json.loads((fixtures_dir / "phishnet_shows_sample.json").read_text())["data"]
    upsert_tour_stubs(db, shows_data)
    for show in shows_data:
        upsert_show(db, show)
    upsert_setlist_songs(
        db, json.loads((fixtures_dir / "phishnet_setlist_show1234567.json").read_text())["data"]
    )
    recompute_run_and_tour_positions(db)
    db.close()
    live.close()

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def seeded_read_db(tmp_path, fixtures_dir):
    """Standalone read DB with the same seed data as seeded_client, for
    tests that need the read conn directly (no FastAPI / lifespan)."""
    from phishpicker.db.connection import apply_schema, open_db
    from phishpicker.ingest.derive import recompute_run_and_tour_positions
    from phishpicker.ingest.pipeline import upsert_tour_stubs
    from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show
    from phishpicker.ingest.songs import upsert_songs
    from phishpicker.ingest.venues import upsert_venues

    db = open_db(tmp_path / "phishpicker.db")
    apply_schema(db)
    upsert_songs(
        db, json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]
    )
    upsert_venues(
        db,
        json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"],
    )
    shows_data = json.loads(
        (fixtures_dir / "phishnet_shows_sample.json").read_text()
    )["data"]
    upsert_tour_stubs(db, shows_data)
    for show in shows_data:
        upsert_show(db, show)
    upsert_setlist_songs(
        db,
        json.loads(
            (fixtures_dir / "phishnet_setlist_show1234567.json").read_text()
        )["data"],
    )
    recompute_run_and_tour_positions(db)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def small_train_db(tmp_path):
    """30 shows, 5 songs. Song 1 always opens set 1; song 2 always closes;
    songs 3/4 fill the middle; song 5 is never played.

    Enough signal for a LambdaRank trained for 50+ rounds to rank
    song 1 > song 5 for the opener slot. Shared between tests/train and
    tests/model so the model's save/load tests can reuse a real booster.
    """
    from phishpicker.db.connection import apply_schema, open_db

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
