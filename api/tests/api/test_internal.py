import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test-key")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "secret-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app

    with TestClient(create_app()) as c:
        yield c


def test_reload_accepts_correct_token(client):
    r = client.post("/internal/reload", headers={"X-Admin-Token": "secret-token"})
    assert r.status_code == 200
    assert r.json()["reloaded"] is True


def test_reload_rejects_wrong_token(client):
    r = client.post("/internal/reload", headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401


def test_reload_rejects_missing_token(client):
    r = client.post("/internal/reload")
    assert r.status_code == 401
