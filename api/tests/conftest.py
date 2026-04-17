import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


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
    upsert_venues(db, json.loads((fixtures_dir / "phishnet_venues_sample.json").read_text())["data"])
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
