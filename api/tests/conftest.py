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
def live_setup(tmp_path, fixtures_dir):
    """Fully seeded read DB + live DB + one live show, for end-to-end sync
    tests that need real DB paths (not live shared connections)."""
    from types import SimpleNamespace

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
    from phishpicker.ingest.derive import recompute_run_and_tour_positions
    from phishpicker.ingest.pipeline import upsert_tour_stubs
    from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show
    from phishpicker.ingest.songs import upsert_songs
    from phishpicker.ingest.venues import upsert_venues
    from phishpicker.live import create_live_show

    db_path = tmp_path / "phishpicker.db"
    live_db_path = tmp_path / "live.db"

    db = open_db(db_path)
    apply_schema(db)
    upsert_songs(
        db, json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]
    )
    upsert_venues(
        db, json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"]
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
    db.close()

    live = open_db(live_db_path)
    apply_live_schema(live)
    show_id = create_live_show(live, "2026-04-23", venue_id=1597)
    live.close()

    return SimpleNamespace(
        db_path=db_path, live_db_path=live_db_path, show_id=show_id
    )


@pytest.fixture
def seeded_live_show(live_conn) -> str:
    """Create a live show directly against live_conn; returns show_id."""
    from phishpicker.live import create_live_show

    return create_live_show(live_conn, "2026-04-23", venue_id=1597)


@pytest.fixture
def live_show_id(seeded_client) -> str:
    """A live show created via the API; returns its show_id."""
    r = seeded_client.post(
        "/live/show", json={"show_date": "2026-04-23", "venue_id": 1597}
    )
    return r.json()["show_id"]


@pytest.fixture
def live_show_with_one_song(seeded_client, live_show_id) -> dict:
    """A live show with a single song already entered in Set 1, slot 1."""
    r = seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    assert r.status_code == 200
    return {"show_id": live_show_id, "song_id": 100}


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


def build_inclusion_runs_db(path: Path) -> None:
    """24 shows over 2024 on two tours. Tour 1: 12 one-offs at distinct venues
    (the last at venue 1). Tour 2: three 3-night runs (venues 2, 3, 4) on
    2024-07-01..03, 07-08..10 and 07-15..17, then one-offs at venues 1, 5, 6
    on 08-10..12. A run = same venue + tour (the app's residency). Show ids are
    5000 + index. Song 1 every show; song 2 every other show; song 3 only on
    night 1 of each run; song 4 rarely; song 5 only on the last show."""
    from phishpicker.db.connection import apply_schema, open_db

    c = open_db(path)
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO tours (tour_id, name) VALUES (1, 'Spring'), (2, 'Summer');
        INSERT INTO songs (song_id, name, first_seen_at, debut_date, original_artist) VALUES
            (1, 'Staple',   '2019-01-01', '2019-01-01', 'Phish'),
            (2, 'Frequent', '2019-01-01', '2019-01-01', 'Phish'),
            (3, 'Opener',   '2019-01-01', '2019-01-01', 'Phish'),
            (4, 'Rare',     '2019-01-01', '2019-01-01', 'Phish'),
            (5, 'Debut',    '2024-12-01', '2024-12-01', 'Phish');
        """
    )
    c.executemany(
        "INSERT INTO venues (venue_id, name) VALUES (?, ?)", [(v, f"V{v}") for v in range(1, 30)]
    )
    shows = []
    # Tour 1: 12 one-off shows, one per week from Jan 6, at venues 10..20 then 1.
    for i in range(12):
        venue = 1 if i == 11 else 10 + i
        shows.append((f"2024-{1 + i // 4:02d}-{6 + 7 * (i % 4):02d}", venue, 1, 1, 1, i + 1))
    # Tour 2: three 3-night runs at venues 2, 3, 4 (consecutive nights), plus 3 one-offs.
    pos = 0
    for venue, start_day in ((2, 1), (3, 8), (4, 15)):
        for night in range(3):
            pos += 1
            shows.append((f"2024-07-{start_day + night:02d}", venue, 2, night + 1, 3, pos))
    for k, venue in enumerate((1, 5, 6)):
        pos += 1
        shows.append((f"2024-08-{10 + k:02d}", venue, 2, 1, 1, pos))

    for idx, (d, venue, tour, rpos, rlen, tpos) in enumerate(shows):
        show_id = 5000 + idx
        c.execute(
            "INSERT INTO shows (show_id, show_date, venue_id, tour_id, run_position, "
            "run_length, tour_position, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (show_id, d, venue, tour, rpos, rlen, tpos, d),
        )
        songs = [1]
        if idx % 2 == 0:
            songs.append(2)
        if rpos == 1:
            songs.append(3)
        if idx % 7 == 0:
            songs.append(4)
        if idx == len(shows) - 1:
            songs.append(5)
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
            [(show_id, "1", p + 1, s) for p, s in enumerate(songs)],
        )
    c.commit()
    c.close()


@pytest.fixture
def inclusion_runs_db(tmp_path) -> Path:
    """Path to a small read DB with multi-night runs (see build_inclusion_runs_db)."""
    path = tmp_path / "phishpicker.db"
    build_inclusion_runs_db(path)
    return path
