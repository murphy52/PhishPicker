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
