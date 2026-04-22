"""Endpoint tests for /live/show/{id}/sync/{start,stop,status}.

Stubs PollerRegistry._sync_fn to a no-op so we don't hit phish.net and
the poller tick is cheap enough to cancel cleanly on teardown.
"""
from datetime import UTC, datetime, timedelta

from phishpicker.db.connection import open_db


def _stub_noop_sync(seeded_client):
    async def noop(**kw):
        return None

    seeded_client.app.state.pollers._sync_fn = noop


def test_sync_start_flips_flag_and_registers_task(seeded_client, live_show_id):
    _stub_noop_sync(seeded_client)

    r = seeded_client.post(
        f"/live/show/{live_show_id}/sync/start",
        json={"show_date": "2026-04-23"},
    )
    assert r.status_code == 200
    assert r.json() == {"started": True}
    assert live_show_id in seeded_client.app.state.pollers._tasks

    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["sync_enabled"] is True


def test_sync_stop_flips_flag_and_removes_task(seeded_client, live_show_id):
    _stub_noop_sync(seeded_client)

    seeded_client.post(
        f"/live/show/{live_show_id}/sync/start",
        json={"show_date": "2026-04-23"},
    )
    r = seeded_client.post(f"/live/show/{live_show_id}/sync/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": True}
    assert live_show_id not in seeded_client.app.state.pollers._tasks

    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["sync_enabled"] is False


def test_sync_status_unknown_show_is_off(seeded_client):
    r = seeded_client.get("/live/show/does-not-exist/sync/status")
    assert r.status_code == 200
    assert r.json() == {
        "state": "off",
        "sync_enabled": False,
        "last_updated": None,
        "last_error": None,
    }


def _write_meta(
    seeded_client, show_id: str, *, enabled: bool, age_seconds: int, error: str | None = None
):
    settings = seeded_client.app.state.settings
    ts = (
        datetime.now(UTC) - timedelta(seconds=age_seconds)
    ).isoformat().replace("+00:00", "Z")
    with open_db(settings.live_db_path) as live:
        live.execute(
            "INSERT INTO live_show_meta (show_id, sync_enabled, last_updated, last_error) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(show_id) DO UPDATE SET "
            "sync_enabled=excluded.sync_enabled, "
            "last_updated=excluded.last_updated, "
            "last_error=excluded.last_error",
            (show_id, 1 if enabled else 0, ts, error),
        )
        live.commit()


def test_sync_status_bucket_live_when_fresh(seeded_client, live_show_id):
    _write_meta(seeded_client, live_show_id, enabled=True, age_seconds=30)
    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["state"] == "live"


def test_sync_status_bucket_stale_after_2min(seeded_client, live_show_id):
    _write_meta(seeded_client, live_show_id, enabled=True, age_seconds=180)
    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["state"] == "stale"


def test_sync_status_bucket_dead_after_10min(seeded_client, live_show_id):
    _write_meta(seeded_client, live_show_id, enabled=True, age_seconds=700)
    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["state"] == "dead"


def test_sync_status_bucket_dead_when_last_error(seeded_client, live_show_id):
    _write_meta(
        seeded_client, live_show_id, enabled=True, age_seconds=10, error="boom"
    )
    status = seeded_client.get(
        f"/live/show/{live_show_id}/sync/status"
    ).json()
    assert status["state"] == "dead"
    assert status["last_error"] == "boom"
