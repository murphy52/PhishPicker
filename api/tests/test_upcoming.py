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
    # the active show. The seed DB has no canonical row for showid=2, so
    # run_position/run_length come back null (residency unknown).
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
        "run_position": None,
        "run_length": None,
    }


def test_upcoming_404s_when_no_future_shows(
    httpx_mock: HTTPXMock, seeded_client
) -> None:
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": []})
    r = seeded_client.get("/upcoming")
    assert r.status_code == 404


def test_upcoming_returns_residency_position_when_canonical_row_known(
    monkeypatch: pytest.MonkeyPatch,
    httpx_mock: HTTPXMock,
    seeded_client,
    tmp_path,
) -> None:
    """When the upcoming show is in the canonical shows table and shares
    venue + tour with other shows, /upcoming surfaces the residency-wide
    position (e.g. 'night 6 of 9') so the UI can render a 'Run N|M' badge.
    Built on the fly from canonical rows — no schema change."""
    # Seed a 9-show residency at venue 1597 / tour 216 around tonight.
    from phishpicker.db.connection import open_db

    with open_db(tmp_path / "phishpicker.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (1597, 'Sphere')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name) VALUES (216, '2026 Sphere Residency')"
        )
        for sid, sdate in [
            (101, "2026-04-16"),
            (102, "2026-04-17"),
            (103, "2026-04-18"),
            (104, "2026-04-23"),
            (105, "2026-04-24"),
            (106, "2026-04-25"),  # the upcoming target
            (107, "2026-04-26"),
            (108, "2026-04-30"),
            (109, "2026-05-01"),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO shows "
                "(show_id, show_date, venue_id, tour_id, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, sdate, 1597, 216, "2026-04-25T00:00:00Z"),
            )
        conn.commit()

    _freeze_now(monkeypatch, datetime(2026, 4, 25, 18, 0, tzinfo=UTC))
    sphere_show = {
        "showid": 106,  # matches the canonical row above
        "showdate": "2026-04-25",
        "artist_name": "Phish",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
    }
    httpx_mock.add_response(url=PHISHNET_URL, json={"data": [sphere_show]})

    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    body = r.json()
    assert body["run_position"] == 6
    assert body["run_length"] == 9


def test_upcoming_suppresses_residency_for_singleton_runs(
    monkeypatch: pytest.MonkeyPatch,
    httpx_mock: HTTPXMock,
    seeded_client,
    tmp_path,
) -> None:
    """A one-off show isn't worth a 'Run 1|1' badge — return null/null."""
    from phishpicker.db.connection import open_db

    with open_db(tmp_path / "phishpicker.db") as conn:
        conn.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (777, 'One-off')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name) VALUES (888, 'Solo gig')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at) "
            "VALUES (200, '2026-06-01', 777, 888, '2026-04-25T00:00:00Z')"
        )
        conn.commit()

    _freeze_now(monkeypatch, datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
    httpx_mock.add_response(
        url=PHISHNET_URL,
        json={
            "data": [
                {
                    "showid": 200,
                    "showdate": "2026-06-01",
                    "artist_name": "Phish",
                    "venue": "One-off",
                    "city": "Somewhere",
                    "state": "CA",
                }
            ]
        },
    )

    body = seeded_client.get("/upcoming").json()
    assert body["run_position"] is None
    assert body["run_length"] is None
