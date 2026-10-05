"""The daily ingest only re-fetches the setlists that can still change (#36).

A full sweep used to cost one phish.net call per show in history (2,261 on
2026-09-27) to learn that nearly nothing had changed. These tests drive the
pipeline with a fake client that counts the calls.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from phishpicker.db.connection import open_db
from phishpicker.ingest.pipeline import (
    full_sweep_due,
    run_ingest,
    select_setlist_fetches,
)

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)  # 11am EDT, the cron's hour


def _show(show_id: int, show_date: str) -> dict:
    return {
        "showid": show_id,
        "showdate": show_date,
        "venueid": None,
        "tourid": None,
        "artistid": 1,
    }


def _setlist(show_id: int, song_ids: list[int], marks: list[str] | None = None) -> list[dict]:
    marks = marks or [","] * len(song_ids)
    return [
        {
            "showid": show_id,
            "set": "1",
            "position": i,
            "songid": sid,
            "song": f"Song {sid}",
            "trans_mark": mark,
        }
        for i, (sid, mark) in enumerate(zip(song_ids, marks, strict=True), start=1)
    ]


class FakePhishNet:
    """Stands in for PhishNetClient: serves fixed data and counts every call."""

    def __init__(self, shows: list[dict], setlists: dict[int, list[dict]]):
        self.shows = shows
        self.setlists = setlists
        self.list_calls = 0
        self.setlist_calls: list[int] = []

    def fetch_songs(self) -> list[dict]:
        self.list_calls += 1
        return []

    def fetch_venues(self) -> list[dict]:
        self.list_calls += 1
        return []

    def fetch_all_shows(self) -> list[dict]:
        self.list_calls += 1
        return list(self.shows)

    def fetch_setlist(self, show_id: int) -> list[dict]:
        self.setlist_calls.append(show_id)
        return [dict(r) for r in self.setlists.get(show_id, [])]

    @property
    def total_calls(self) -> int:
        return self.list_calls + len(self.setlist_calls)


OLD = 1  # 1987, has a setlist
CANCELLED = 2  # 2020 summer tour: listed by phish.net, never played
RECENT = 3  # 15 days before NOW
LAST_NIGHT = 4
FUTURE = 5
BACK_ADDED = 6  # a historic show phish.net adds after we first synced


def _history() -> tuple[list[dict], dict[int, list[dict]]]:
    shows = [
        _show(OLD, "1987-05-20"),
        _show(CANCELLED, "2020-08-07"),
        _show(RECENT, "2026-09-20"),
        _show(LAST_NIGHT, "2026-10-04"),
        _show(FUTURE, "2026-10-09"),
    ]
    setlists = {
        OLD: _setlist(OLD, [10, 11]),
        RECENT: _setlist(RECENT, [20, 21, 22]),
        LAST_NIGHT: _setlist(LAST_NIGHT, [30, 31]),
    }
    return shows, setlists


@pytest.fixture
def synced(tmp_path: Path):
    """A DB that had a full sweep yesterday, plus the phish.net it came from."""
    conn = open_db(tmp_path / "phishpicker.db")
    shows, setlists = _history()
    run_ingest(conn, FakePhishNet(shows, setlists), now=NOW - timedelta(days=1))
    return conn, shows, setlists


def _rows(conn, show_id: int) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT set_number, position, song_id, trans_mark FROM setlist_songs "
            "WHERE show_id = ? ORDER BY set_number, position",
            (show_id,),
        )
    ]


def test_first_run_on_an_empty_db_is_a_full_sweep(tmp_path: Path):
    conn = open_db(tmp_path / "phishpicker.db")
    shows, setlists = _history()
    client = FakePhishNet(shows, setlists)

    stats = run_ingest(conn, client, now=NOW)

    assert stats["mode"] == "full"
    # Every show that has happened; never the future one.
    assert sorted(client.setlist_calls) == [OLD, CANCELLED, RECENT, LAST_NIGHT]
    assert _rows(conn, OLD) == [("1", 1, 10, ","), ("1", 2, 11, ",")]


def test_incremental_run_fetches_only_new_and_recent_shows(synced):
    conn, shows, setlists = synced
    shows = [*shows, _show(BACK_ADDED, "1995-12-31")]
    setlists = {**setlists, BACK_ADDED: _setlist(BACK_ADDED, [40])}
    client = FakePhishNet(shows, setlists)

    stats = run_ingest(conn, client, now=NOW)

    assert stats["mode"] == "incremental"
    # Recent shows + the one we have never seen. Not the 1987 show, not the
    # cancelled one (no setlist exists, so "missing" would refetch it forever),
    # not the future one.
    assert sorted(client.setlist_calls) == [RECENT, LAST_NIGHT, BACK_ADDED]
    # songs + venues + shows list: still one call each.
    assert client.list_calls == 3
    assert stats["shows"] == len(shows)
    assert stats["setlists_fetched"] == 3
    assert _rows(conn, BACK_ADDED) == [("1", 1, 40, ",")]


def test_full_flag_fetches_every_show_that_has_happened(synced):
    conn, shows, setlists = synced
    client = FakePhishNet(shows, setlists)

    stats = run_ingest(conn, client, full=True, now=NOW)

    assert stats["mode"] == "full"
    assert sorted(client.setlist_calls) == [OLD, CANCELLED, RECENT, LAST_NIGHT]


def test_full_sweep_runs_by_itself_once_a_week(tmp_path: Path):
    shows, setlists = _history()

    conn = open_db(tmp_path / "week.db")
    run_ingest(conn, FakePhishNet(shows, setlists), now=NOW - timedelta(days=7))
    week_later = FakePhishNet(shows, setlists)
    assert run_ingest(conn, week_later, now=NOW)["mode"] == "full"
    assert OLD in week_later.setlist_calls

    conn = open_db(tmp_path / "six.db")
    run_ingest(conn, FakePhishNet(shows, setlists), now=NOW - timedelta(days=6))
    six_days = FakePhishNet(shows, setlists)
    assert run_ingest(conn, six_days, now=NOW)["mode"] == "incremental"
    assert OLD not in six_days.setlist_calls


def test_a_forced_full_sweep_resets_the_weekly_clock(synced):
    conn, shows, setlists = synced
    run_ingest(conn, FakePhishNet(shows, setlists), full=True, now=NOW + timedelta(days=5))
    # 7 days after the scheduled sweep, but only 2 after the forced one.
    stats = run_ingest(conn, FakePhishNet(shows, setlists), now=NOW + timedelta(days=7))
    assert stats["mode"] == "incremental"


def test_an_incremental_run_does_not_reset_the_weekly_clock(synced):
    conn, shows, setlists = synced
    for d in range(6):
        run_ingest(conn, FakePhishNet(shows, setlists), now=NOW + timedelta(days=d - 1, hours=1))
    stats = run_ingest(conn, FakePhishNet(shows, setlists), now=NOW + timedelta(days=6))
    assert stats["mode"] == "full"


def test_a_corrected_recent_setlist_is_updated(synced):
    conn, shows, setlists = synced
    # phish.net fixes a segue and swaps the closer the day after the show.
    corrected = {**setlists, LAST_NIGHT: _setlist(LAST_NIGHT, [30, 32], [">", ","])}

    stats = run_ingest(conn, FakePhishNet(shows, corrected), now=NOW)

    assert _rows(conn, LAST_NIGHT) == [("1", 1, 30, ">"), ("1", 2, 32, ",")]
    assert stats["setlists_changed"] == 1


def test_an_unchanged_setlist_is_not_rewritten(synced):
    conn, shows, setlists = synced
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    stats = run_ingest(conn, FakePhishNet(shows, setlists), now=NOW)

    conn.set_trace_callback(None)
    writes = [
        s
        for s in statements
        if s.lstrip().startswith(("DELETE FROM setlist_songs", "INSERT INTO setlist_songs"))
    ]
    assert writes == []
    assert stats["setlists_fetched"] == 2
    assert stats["setlists_changed"] == 0
    assert stats["setlist_rows"] == 0


def test_a_failed_setlist_fetch_is_counted_and_skipped(synced):
    from phishpicker.phishnet.client import PhishNetError

    conn, shows, setlists = synced

    class Flaky(FakePhishNet):
        def fetch_setlist(self, show_id: int) -> list[dict]:
            if show_id == RECENT:
                raise PhishNetError("HTTP 503 from setlists")
            return super().fetch_setlist(show_id)

    stats = run_ingest(conn, Flaky(shows, setlists), now=NOW)

    assert stats["setlist_errors"] == 1
    assert _rows(conn, RECENT) == [("1", 1, 20, ","), ("1", 2, 21, ","), ("1", 3, 22, ",")]


# --- the pure rules ----------------------------------------------------------


def test_recent_window_is_inclusive_of_its_first_day():
    today = date(2026, 10, 5)
    shows = [
        _show(1, "2026-09-04"),  # 31 days ago: outside
        _show(2, "2026-09-05"),  # 30 days ago: inside
        _show(3, "2026-10-05"),  # today
        _show(4, "2026-10-06"),  # tomorrow
    ]
    picked = select_setlist_fetches(shows, known_ids={1, 2, 3, 4}, today=today, full=False)
    assert [s["showid"] for s in picked] == [2, 3]


def test_unknown_shows_are_fetched_whatever_their_date_but_never_the_future():
    today = date(2026, 10, 5)
    shows = [_show(1, "1983-12-02"), _show(2, "2027-01-30")]
    picked = select_setlist_fetches(shows, known_ids=set(), today=today, full=False)
    assert [s["showid"] for s in picked] == [1]
    picked = select_setlist_fetches(shows, known_ids=set(), today=today, full=True)
    assert [s["showid"] for s in picked] == [1]


def test_full_sweep_due_counts_calendar_days():
    monday_11am = datetime(2026, 10, 5, 15, 0, 5, tzinfo=UTC)
    assert full_sweep_due(None, monday_11am)
    # A week to the calendar day is due even if the clock reads a few seconds
    # earlier, so the sweep doesn't drift a day later every week.
    assert full_sweep_due(monday_11am, monday_11am + timedelta(days=7, seconds=-10))
    assert not full_sweep_due(monday_11am, monday_11am + timedelta(days=6, hours=8))


# --- CLI ------------------------------------------------------------------------


@pytest.mark.parametrize(("argv", "expected"), [([], None), (["--full"], True)])
def test_cli_ingest_full_flag(monkeypatch, tmp_path, argv, expected):
    import sys

    import phishpicker.cli as cli

    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    seen: dict = {}

    def fake_run_ingest(conn, client, artist_id=None, *, full=None):
        seen["full"] = full
        return {"mode": "full" if full else "incremental"}

    monkeypatch.setattr(cli, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(sys, "argv", ["phishpicker", "ingest", *argv])

    assert cli.main() == 0
    assert seen == {"full": expected}
