from fastapi.testclient import TestClient


def test_meta_returns_expected_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/meta")
    assert r.status_code == 200
    body = r.json()
    assert {"shows_count", "songs_count", "data_snapshot_at"} <= set(body)


def test_meta_reports_last_setlist_date(tmp_path, monkeypatch):
    """`last_setlist_date` is MAX(show_date) over shows that actually have
    setlist rows ingested. Catches the case where a future show is in the
    DB but its setlist hasn't been pulled — the bug that hid the residency-
    suppression filter mid-Sphere.
    """
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    c = open_db(tmp_path / "phishpicker.db")
    apply_schema(c)
    apply_live_schema(open_db(tmp_path / "live.db"))
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES (1, 'A', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (1, 'Sphere');
        -- Two future-dated rows AND one past-dated row that has a setlist.
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (10, '2026-04-23', 1, '2026-04-24'),  -- has setlist
            (20, '2026-04-30', 1, '2026-04-25'),  -- empty (upcoming)
            (30, '2027-01-30', 1, '2026-04-25');  -- empty (placeholder)
        INSERT INTO setlist_songs (show_id, set_number, position, song_id)
        VALUES (10, '1', 1, 1);
        """
    )
    c.commit()
    c.close()

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/meta")
    body = r.json()
    # latest_show_date sees the placeholder; last_setlist_date sees the
    # most recent show that actually has a setlist.
    assert body["latest_show_date"] == "2027-01-30"
    assert body["last_setlist_date"] == "2026-04-23"


def test_meta_last_setlist_date_null_when_no_setlists(tmp_path, monkeypatch):
    """Empty DB returns last_setlist_date=None instead of erroring."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/meta")
    body = r.json()
    assert body["last_setlist_date"] is None


def test_meta_reports_model_sha(tmp_path, monkeypatch):
    """`model_sha` is a non-empty string identifying the loaded scorer.
    Used as a cache key for slot_predictions_cache. Heuristic fallback
    uses a sentinel so cache rows remain well-formed."""
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/meta")
    body = r.json()
    assert "model_sha" in body
    assert isinstance(body["model_sha"], str)
    assert len(body["model_sha"]) > 0
    # Heuristic fallback (no model.lgb) → sentinel.
    assert body["model_sha"] == "heuristic-v1"
