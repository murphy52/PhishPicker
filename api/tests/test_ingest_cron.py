"""Schedule logic for the ingest-cron sidecar.

The sidecar runs in a Docker container next to the API and triggers
`phishpicker ingest` daily at 11am EDT. We test the pure schedule function
here; the long-running loop wrapper is exercised by the sidecar itself.
"""

from datetime import datetime
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
