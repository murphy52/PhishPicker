"""The API container starts uvicorn directly (no init-db step), so the app
must apply the live schema itself at startup — otherwise new tables like
live_score_state (and the E2/E3 CHECK migration) never reach prod."""

from fastapi.testclient import TestClient


def test_app_startup_initializes_live_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test-key")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    # The read DB is owned by the ingest pipeline and always exists in prod;
    # create it (schema only) so create_show's read dependency resolves.
    from phishpicker.db.connection import apply_schema, open_db

    read = open_db(tmp_path / "phishpicker.db")
    apply_schema(read)
    read.close()

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        r = client.post("/live/show", json={"show_date": "2026-07-07"})
        assert r.status_code == 200
        assert r.json()["show_id"]
