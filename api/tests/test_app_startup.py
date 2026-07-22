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


def test_startup_resumes_sync_pollers(tmp_path, monkeypatch):
    """The poller registry is in-memory, so a container restart mid-show used
    to orphan sync: the DB said enabled, the UI said enabled, but no reconciler
    ran until a manual /sync/now. Startup must resume pollers for recent,
    un-finalized, sync-enabled shows — and only those."""
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("PHISHNET_API_KEY", "test-key")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))

    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    read = open_db(tmp_path / "phishpicker.db")
    apply_schema(read)
    read.close()

    from phishpicker.live import create_live_show

    live = open_db(tmp_path / "live.db")
    apply_live_schema(live)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    def seed(show_date, sync_enabled, finalized=False):
        sid = create_live_show(live, show_date, venue_id=None)
        live.execute(
            "INSERT INTO live_show_meta (show_id, sync_enabled) VALUES (?, ?) "
            "ON CONFLICT(show_id) DO UPDATE SET sync_enabled=excluded.sync_enabled",
            (sid, int(sync_enabled)),
        )
        if finalized:
            live.execute(
                "INSERT INTO scorecards (show_id, show_date, finalized_at, combined, "
                "foresight_total, live_total, ppps, max_streak, payload) "
                "VALUES (?, ?, ?, 0, 0, 0, 0, 0, '{}')",
                (sid, show_date, datetime.now(UTC).isoformat()),
            )
        live.commit()
        return sid

    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    two_ago = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
    active = seed(today, sync_enabled=True)
    seed("2026-01-01", sync_enabled=True)  # too old
    seed(two_ago, sync_enabled=True, finalized=True)  # already scored
    seed(yesterday, sync_enabled=False)  # sync turned off
    live.close()

    # Keep resumed pollers from hitting phish.net: swap the tick fn for a no-op.
    import phishpicker.live_sync as live_sync

    async def _noop_sync(**kwargs):
        return None

    monkeypatch.setattr(live_sync, "_default_sync", _noop_sync)

    from phishpicker.app import create_app

    with TestClient(create_app()) as client:
        tasks = client.app.state.pollers._tasks
        assert set(tasks) == {active}
