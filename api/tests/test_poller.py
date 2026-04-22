import asyncio

import pytest

from phishpicker.live_sync import PollerRegistry


async def test_poller_registry_runs_sync_on_interval():
    calls: list[tuple] = []

    async def fake_sync(**kw):
        calls.append((kw["show_id"], kw["show_date"]))

    reg = PollerRegistry(sync_fn=fake_sync)
    try:
        await reg.start("abc", show_date="2026-04-23", interval=0.05)
        await asyncio.sleep(0.17)
    finally:
        await reg.stop("abc")
    assert len(calls) >= 2
    assert all(c == ("abc", "2026-04-23") for c in calls)


async def test_poller_registry_stop_is_idempotent():
    reg = PollerRegistry()
    await reg.stop("nothing")  # must not raise


async def test_poller_registry_start_idempotent_for_same_show():
    async def sync_fn(**kw):
        return None

    reg = PollerRegistry(sync_fn=sync_fn)
    try:
        await reg.start("a", show_date="x", interval=1)
        await reg.start("a", show_date="x", interval=1)  # no-op
        assert len(reg._tasks) == 1
    finally:
        await reg.stop("a")


async def test_poller_registry_records_last_error():
    async def bad_sync(**kw):
        raise RuntimeError("boom")

    reg = PollerRegistry(sync_fn=bad_sync)
    try:
        await reg.start("z", show_date="2026-04-23", interval=0.05)
        await asyncio.sleep(0.08)
    finally:
        await reg.stop("z")
    assert "boom" in (reg.last_error("z") or "")


async def test_poller_registry_stop_all_cancels_everything():
    async def sync_fn(**kw):
        await asyncio.sleep(10)

    reg = PollerRegistry(sync_fn=sync_fn)
    await reg.start("a", show_date="x", interval=10)
    await reg.start("b", show_date="y", interval=10)
    assert len(reg._tasks) == 2
    await reg.stop_all()
    assert reg._tasks == {}


# Silence asyncio's "task was destroyed but pending" warnings that are
# harmless here but spammy if tests abort mid-sleep.
@pytest.fixture(autouse=True)
def _silence_pending_task_warnings(caplog):
    import logging

    caplog.set_level(logging.ERROR, logger="asyncio")
    yield
