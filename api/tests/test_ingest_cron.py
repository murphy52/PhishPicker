"""Schedule logic for the ingest-cron sidecar.

The sidecar runs in a Docker container next to the API and triggers
`phishpicker ingest` daily at 11am EDT. We test the pure schedule function
here; the long-running loop wrapper is exercised by the sidecar itself.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from phishpicker.ingest_cron import next_run_at

EDT = ZoneInfo("America/New_York")


def test_next_run_when_already_past_target_today_rolls_to_tomorrow():
    """If now is after 11am EDT today, the next run is 11am EDT tomorrow."""
    now = datetime(2026, 4, 26, 18, 30, tzinfo=EDT)
    nxt = next_run_at(now, hour=11, tz=EDT)
    assert nxt == datetime(2026, 4, 27, 11, 0, tzinfo=EDT)


def test_next_run_when_before_target_today_runs_today():
    """If now is before 11am EDT today, the next run is today at 11am EDT."""
    now = datetime(2026, 4, 26, 9, 0, tzinfo=EDT)
    nxt = next_run_at(now, hour=11, tz=EDT)
    assert nxt == datetime(2026, 4, 26, 11, 0, tzinfo=EDT)


def test_next_run_at_exactly_target_rolls_to_tomorrow():
    """At exactly 11:00:00, treat as 'just ran' and schedule tomorrow.
    Avoids a tight loop where now == target and sleep is 0."""
    now = datetime(2026, 4, 26, 11, 0, tzinfo=EDT)
    nxt = next_run_at(now, hour=11, tz=EDT)
    assert nxt == datetime(2026, 4, 27, 11, 0, tzinfo=EDT)


def test_next_run_handles_dst_spring_forward():
    """In US, DST jumps from 2am EST to 3am EDT on the second Sunday of
    March. 11am-local is unambiguous before and after; verify the schedule
    keeps targeting 11am-local across the transition."""
    # 2026-03-08 is the second Sunday of March, US DST starts that day.
    now_before = datetime(2026, 3, 7, 12, 0, tzinfo=EDT)  # Saturday afternoon
    nxt = next_run_at(now_before, hour=11, tz=EDT)
    # Should be Sunday 11am — but Sunday's UTC offset is now -04, not -05.
    assert nxt == datetime(2026, 3, 8, 11, 0, tzinfo=EDT)
    # Sanity: this datetime is in the post-spring-forward fold.
    assert nxt.utcoffset().total_seconds() == -4 * 3600


@pytest.mark.parametrize("hour", [0, 11, 23])
def test_next_run_returns_aware_datetime_at_requested_hour(hour: int):
    now = datetime(2026, 4, 26, 5, 0, tzinfo=EDT)
    nxt = next_run_at(now, hour=hour, tz=EDT)
    assert nxt.tzinfo is not None
    assert nxt.hour == hour
    assert nxt.minute == 0
    assert nxt.second == 0
    assert nxt > now


# --- phishvs publish cadence ------------------------------------------------


class _Settings:
    phishvs_publish_url = "https://phishvs.test/publish"
    phishvs_publish_key_id = "k1"
    phishvs_publish_secret = "s3cret"
    db_path = "unused"


def _no_scorer():
    raise AssertionError("scorer must only be loaded when a bundle actually goes out")


@pytest.fixture
def publish_calls(monkeypatch):
    """Stub the DB lookup (a NJ show on 2026-04-23) and the publish itself;
    returns the list of dates publish_show was called with."""
    from unittest.mock import MagicMock

    from phishpicker import publish as mod

    calls: list[str] = []
    monkeypatch.setattr(mod, "open_db", lambda *a, **k: MagicMock())
    monkeypatch.setattr(
        mod,
        "show_on",
        lambda _read, date: (
            {"show_date": date, "venue_id": 1, "venue": "x", "tz": EDT}
            if date == "2026-04-23"
            else None
        ),
    )
    monkeypatch.setattr(mod, "publish_show", lambda _s, _sc, date, **_k: calls.append(date) or {})
    return calls


def _ingested(now: datetime) -> dict:
    from phishpicker.publish import mark_ingested

    state: dict = {}
    mark_ingested(state, now)
    return state


def test_publish_tick_waits_for_ingest_then_hourly_until_lock(publish_calls):
    """No bundle before the day's ingest (the bracket would predate last
    night's setlist); first publish on the tick right after it; then hourly;
    nothing at or after the 19:30 lock."""
    from phishpicker.publish import mark_ingested, publish_tick

    state: dict = {}
    settings, load = _Settings(), lambda: object()
    ingest_at = datetime(2026, 4, 23, 11, 0, tzinfo=EDT)
    # 10-minute ticks from 08:00 ET on show day through the 19:30 lock and past it.
    start = datetime(2026, 4, 23, 8, 0, tzinfo=EDT)
    sent = []
    for i in range(6 * 14):  # -> 21:50
        t = start + timedelta(minutes=10 * i)
        if t == ingest_at:
            mark_ingested(state, t)
        if publish_tick(settings, load, state, t):
            sent.append(t)
    assert sent[0] == ingest_at
    assert all(b - a == timedelta(hours=1) for a, b in zip(sent, sent[1:], strict=False))
    assert sent[-1] == datetime(2026, 4, 23, 19, 0, tzinfo=EDT)
    assert publish_calls == ["2026-04-23"] * len(sent)


def test_publish_tick_ignores_yesterdays_ingest(publish_calls):
    """A startup ingest before the 6am rollover marks yesterday, not today."""
    from phishpicker.publish import publish_tick

    state = _ingested(datetime(2026, 4, 23, 2, 0, tzinfo=EDT))
    now = datetime(2026, 4, 23, 12, 0, tzinfo=EDT)
    assert not publish_tick(_Settings(), _no_scorer, state, now)
    assert publish_calls == []


def test_publish_tick_respects_lock_override(publish_calls):
    from phishpicker.publish import publish_tick

    now = datetime(2026, 4, 23, 12, 0, tzinfo=EDT)
    assert not publish_tick(_Settings(), _no_scorer, _ingested(now), now, lock_local="11:00")
    assert publish_tick(_Settings(), lambda: object(), _ingested(now), now, lock_local="12:01")


def test_publish_tick_noop_without_show_or_settings(publish_calls):
    from phishpicker.publish import publish_tick

    # No canonical show on the (rollover-adjusted) date.
    now = datetime(2026, 4, 22, 12, 0, tzinfo=EDT)
    assert not publish_tick(_Settings(), _no_scorer, _ingested(now), now)

    class Unset(_Settings):
        phishvs_publish_secret = ""

    now = datetime(2026, 4, 23, 12, 0, tzinfo=EDT)
    assert not publish_tick(Unset(), _no_scorer, _ingested(now), now)
    assert publish_calls == []


def test_publish_tick_survives_a_failed_publish(publish_calls, monkeypatch):
    """A failed POST is logged, not raised; the hourly clock does not advance so
    the next tick retries."""
    from phishpicker import publish as mod

    def boom(*_a, **_k):
        raise RuntimeError("phishvs down")

    monkeypatch.setattr(mod, "publish_show", boom)
    now = datetime(2026, 4, 23, 12, 0, tzinfo=EDT)
    state = _ingested(now)
    assert not mod.publish_tick(_Settings(), lambda: object(), state, now)
    assert "last_published_at" not in state


def test_publish_warns_once_per_day_after_a_failed_attempt(publish_calls, caplog):
    """Holding before the 11:00 ingest is the normal morning, not a warning;
    only a failed attempt today warns, and then once."""
    from phishpicker.publish import publish_tick

    state: dict = {}
    held = lambda: [r.message for r in caplog.records if "no successful ingest" in r.message]  # noqa: E731
    with caplog.at_level("WARNING", logger="phishpicker.publish"):
        for h in (8, 9, 10):
            publish_tick(_Settings(), _no_scorer, state, datetime(2026, 4, 23, h, 0, tzinfo=EDT))
        assert held() == []
        state["last_ingest_attempt_at"] = datetime(2026, 4, 23, 11, 0, tzinfo=EDT)
        for m in (0, 10, 20):
            publish_tick(_Settings(), _no_scorer, state, datetime(2026, 4, 23, 11, m, tzinfo=EDT))
    assert held() == ["publish: show on 2026-04-23 but no successful ingest yet; holding"]


def test_configured_does_not_log():
    from phishpicker.publish import configured

    class Unset(_Settings):
        phishvs_publish_url = ""

    assert configured(_Settings()) and not configured(Unset())


# --- show-day ingest retry ----------------------------------------------------


def test_ingest_retry_due_only_on_show_days_after_a_failed_attempt(publish_calls):
    from phishpicker.publish import ingest_retry_due

    show_day = datetime(2026, 4, 23, 11, 0, tzinfo=EDT)
    # Nothing attempted today -> not due: the 11:00 schedule is the only
    # scheduled ingest; a retry needs a failed attempt TODAY.
    assert not ingest_retry_due(_Settings(), {}, show_day)
    # Yesterday's (02:00, pre-rollover) startup attempt is not "today" either,
    # however stale — the first 6am tick must not ingest + freeze early.
    stale = {"last_ingest_attempt_at": datetime(2026, 4, 23, 2, 0, tzinfo=EDT)}
    assert not ingest_retry_due(_Settings(), stale, datetime(2026, 4, 23, 6, 10, tzinfo=EDT))
    # A failed 11:00 attempt makes 11:30 due (but not 11:20).
    state = {"last_ingest_attempt_at": show_day}
    assert not ingest_retry_due(_Settings(), state, show_day + timedelta(minutes=20))
    assert ingest_retry_due(_Settings(), state, show_day + timedelta(minutes=30))
    # Already ingested today -> never.
    assert not ingest_retry_due(_Settings(), _ingested(show_day), show_day + timedelta(hours=2))
    # Not a show day -> never, however stale the last attempt.
    assert not ingest_retry_due(_Settings(), {}, datetime(2026, 4, 22, 11, 0, tzinfo=EDT))


@pytest.fixture
def cron_stubs(monkeypatch):
    """Stub the subprocess ingest (a scripted list of exit codes), the close-out
    pass, the watcher and the scorer load."""
    from phishpicker import ingest_cron as cron

    codes: list[int] = []
    passes: list[dict] = []
    monkeypatch.setattr(cron, "_run_ingest", lambda: codes.pop(0))
    monkeypatch.setattr(cron, "_daily_pass", lambda **kw: passes.append(kw))
    monkeypatch.setattr(cron, "_watch_tick", lambda _state: None)
    monkeypatch.setattr(cron, "_load_scorer", lambda: (_Settings(), object()))
    return codes, passes


def test_failed_ingest_neither_freezes_nor_unlocks_publish(cron_stubs):
    from phishpicker.ingest_cron import _ingest_and_pass

    codes, passes = cron_stubs
    codes.append(1)
    state: dict = {}
    now = datetime(2026, 4, 23, 11, 0, tzinfo=EDT)
    _ingest_and_pass(state, now)
    assert passes == [{"freeze_today": False}]
    assert "ingested_date" not in state
    assert state["last_ingest_attempt_at"] == now

    codes.append(0)
    _ingest_and_pass(state, now + timedelta(minutes=30))
    assert passes[-1] == {"freeze_today": True}
    assert state["ingested_date"] == "2026-04-23"


def test_loop_retries_failed_ingest_on_show_day_then_publishes(cron_stubs, publish_calls):
    """11:00 ingest fails -> no publish; 11:30 retry succeeds -> publish on that
    tick. Ticks in between neither re-ingest nor publish."""
    from phishpicker.ingest_cron import _ingest_and_pass, _loop_tick

    codes, passes = cron_stubs
    state: dict = {}
    publish_state: dict = {}
    t0 = datetime(2026, 4, 23, 11, 0, tzinfo=EDT)
    codes.append(1)
    _ingest_and_pass(publish_state, t0)  # the scheduled 11:00 ingest
    codes.append(0)  # what the retry will get
    for m in (0, 10, 20):
        _loop_tick(_Settings(), state, publish_state, t0 + timedelta(minutes=m))
        assert publish_calls == [] and codes == [0]
    _loop_tick(_Settings(), state, publish_state, t0 + timedelta(minutes=30))
    assert codes == [] and passes[-1] == {"freeze_today": True}
    assert publish_calls == ["2026-04-23"]
    assert publish_state["last_published_at"] == t0 + timedelta(minutes=30)


def test_loop_does_not_retry_on_a_non_show_day(cron_stubs, publish_calls):
    from phishpicker.ingest_cron import _loop_tick

    codes, _ = cron_stubs
    codes.append(0)
    _loop_tick(_Settings(), {}, {}, datetime(2026, 4, 22, 11, 30, tzinfo=EDT))
    assert codes == [0] and publish_calls == []
