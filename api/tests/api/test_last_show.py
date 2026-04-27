import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    c = open_db(tmp_path / "phishpicker.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name, city, state) VALUES (10, 'Sphere', 'Las Vegas', 'NV');
        INSERT INTO tours (tour_id, name) VALUES (77, '2026 Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at) VALUES
            (102, '2026-04-25', 10, 77, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (102, '1', 1, 1);
        """
    )
    c.commit()
    c.close()
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        yield cl


def test_last_show_returns_metadata_only(client):
    r = client.get("/last-show")
    assert r.status_code == 200
    body = r.json()
    assert body["show_id"] == 102
    assert body["show_date"] == "2026-04-25"
    assert body["venue"] == "Sphere"
    assert "slots" not in body  # metadata-only — no per-slot ranks


def test_last_show_returns_404_when_no_completed_show(tmp_path, monkeypatch):
    """Empty DB → 404 → picker hides footer link."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))
    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        r = cl.get("/last-show")
    assert r.status_code == 404


def test_review_returns_setlist_with_ranks(client):
    r = client.get("/last-show/review")
    assert r.status_code == 200
    body = r.json()
    assert body["show"]["show_id"] == 102
    assert isinstance(body["slots"], list)
    assert len(body["slots"]) >= 1
    s = body["slots"][0]
    assert s["set_number"] == "1"
    assert s["position"] == 1
    assert s["actual_song_id"] == 1
    assert s["actual_song"] == "A"
    assert "actual_rank" in s


def test_review_cache_hit_serves_stored_rank(client, tmp_path):
    """First call populates the cache. Mutate the cache row directly,
    then call again — if the response reflects the mutation, the cache
    was served (no recompute). If it reflects the model's true rank,
    the cache was bypassed."""
    from phishpicker.db.connection import open_db

    # Prime the cache.
    r1 = client.get("/last-show/review")
    assert r1.status_code == 200
    assert len(r1.json()["slots"]) >= 1

    # Tamper: set every cached actual_rank to a sentinel.
    db = open_db(tmp_path / "phishpicker.db", read_only=False)
    try:
        db.execute("UPDATE slot_predictions_cache SET actual_rank = 999")
        db.commit()
    finally:
        db.close()

    # Second call must return the tampered value — proves cache served.
    r2 = client.get("/last-show/review")
    assert r2.status_code == 200
    assert all(s["actual_rank"] == 999 for s in r2.json()["slots"])


def test_review_404_when_no_completed_show(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))
    from phishpicker.app import create_app
    with TestClient(create_app()) as cl:
        r = cl.get("/last-show/review")
    assert r.status_code == 404
