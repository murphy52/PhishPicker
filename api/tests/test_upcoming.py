"""Date-portable regression tests for /upcoming.

The endpoint computes "today" as `datetime.now(UTC) - 15h` so the rollover
to the next show happens at 15:00 UTC = 08:00 PT / 11:00 ET — comfortably
after a typical 7pm Phish show ends. These tests freeze the clock at
specific moments around a show date to assert the rollover behavior is
correct from both an East-coast (watching from JAX) and West-coast
(in Vegas with the band) viewpoint.
"""

from datetime import UTC, datetime

import pytest
from pytest_httpx import HTTPXMock

# Three Sphere residency nights — fixed dates so the test is deterministic.
SPHERE_SHOWS = [
    {
        "showid": 1,
        "showdate": "2026-04-24",
        "artist_name": "Phish",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
    },
    {
        "showid": 2,
        "showdate": "2026-04-25",
        "artist_name": "Phish",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
    },
    {
        "showid": 3,
        "showdate": "2026-04-26",
        "artist_name": "Phish",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
    },
]

PHISHNET_URL = (
    "https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate"
)


def _freeze_now(monkeypatch: pytest.MonkeyPatch, frozen: datetime) -> None:
    """Pin phishpicker.app.datetime.now() to `frozen`."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 — emulate datetime.now signature
            return frozen

    monkeypatch.setattr("phishpicker.app.datetime", _Frozen)


def test_upcoming_during_show_returns_tonights_show_from_east_coast(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock, seeded_client
) -> None:
    # 11:30pm ET on 2026-04-25 = 8:30pm PT = 03:30 UTC on 4/26.
    # Today's Sphere show is in progress; we should see 4/25, not 4/26.
    _freeze_now(monkeypatch, datetime(2026, 4, 26, 3, 30, tzinfo=UTC))
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": SPHERE_SHOWS})

    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    assert r.json()["show_date"] == "2026-04-25"


def test_upcoming_late_after_show_still_returns_tonights_show(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock, seeded_client
) -> None:
    # 10pm PT on 2026-04-25 = 05:00 UTC on 4/26. Show has ended but the
    # rollover (08:00 PT next morning) hasn't fired yet — keep 4/25 sticky
    # so the user reviewing the setlist isn't yanked to tomorrow.
    _freeze_now(monkeypatch, datetime(2026, 4, 26, 5, 0, tzinfo=UTC))
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": SPHERE_SHOWS})

    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    assert r.json()["show_date"] == "2026-04-25"


def test_upcoming_after_morning_rollover_returns_next_show(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock, seeded_client
) -> None:
    # 8:30am PT on 2026-04-26 = 15:30 UTC on 4/26 — past the rollover.
    # Should now advance to the next residency night.
    _freeze_now(monkeypatch, datetime(2026, 4, 26, 15, 30, tzinfo=UTC))
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": SPHERE_SHOWS})

    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    assert r.json()["show_date"] == "2026-04-26"


def test_upcoming_returns_full_payload_with_la_timezone(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock, seeded_client
) -> None:
    # Locks in the venue→tz mapping (NV → America/Los_Angeles) and the
    # 19:00 hardcoded local start time. Frozen at a moment where 4/25 is
    # the active show.
    _freeze_now(monkeypatch, datetime(2026, 4, 25, 18, 0, tzinfo=UTC))
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": SPHERE_SHOWS})

    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    assert r.json() == {
        "show_id": 2,
        "show_date": "2026-04-25",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
        "timezone": "America/Los_Angeles",
        "start_time_local": "19:00",
    }


def test_upcoming_404s_when_no_future_shows(
    httpx_mock: HTTPXMock, seeded_client
) -> None:
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": []})
    r = seeded_client.get("/upcoming")
    assert r.status_code == 404
