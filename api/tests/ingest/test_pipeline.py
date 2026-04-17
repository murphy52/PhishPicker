import json
from pathlib import Path

from pytest_httpx import HTTPXMock

from phishpicker.db.connection import open_db
from phishpicker.ingest.pipeline import run_full_ingest
from phishpicker.phishnet.client import PhishNetClient


def test_full_ingest_populates_all_tables(
    tmp_path: Path, fixtures_dir: Path, httpx_mock: HTTPXMock
):
    # Mock all four phish.net endpoints using existing fixtures
    httpx_mock.add_response(
        url="https://api.phish.net/v5/songs.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_songs_sample.json").read_text(),
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/venues.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_venues_sample.json").read_text(),
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=desc",
        text=(fixtures_dir / "phishnet_shows_sample.json").read_text(),
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showid/1234567.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_setlist_show1234567.json").read_text(),
    )

    conn = open_db(tmp_path / "test.db")
    client = PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5")

    stats = run_full_ingest(conn, client)

    # Assert return dict has the expected keys
    assert set(stats.keys()) == {"songs", "venues", "shows", "setlist_rows"}

    # Assert counts
    assert stats["songs"] == 2
    assert stats["venues"] == 1
    assert stats["shows"] == 1
    assert stats["setlist_rows"] == 2

    # Assert DB row counts
    assert conn.execute("SELECT count(*) FROM songs").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM venues").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM shows").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM setlist_songs").fetchone()[0] == 2

    # Assert run_position was computed (not NULL)
    row = conn.execute("SELECT run_position FROM shows WHERE show_id = 1234567").fetchone()
    assert row is not None
    assert row["run_position"] is not None


def test_setlist_fetch_failure_does_not_abort_ingest(
    tmp_path: Path, fixtures_dir: Path, httpx_mock: HTTPXMock
):
    """A transient setlist error on one show should be logged and skipped; other shows succeed."""
    two_shows = json.dumps(
        {
            "error": False,
            "data": [
                {"showid": 1234567, "showdate": "2024-07-21", "venueid": 500, "tourid": 77},
                {"showid": 1234568, "showdate": "2024-07-22", "venueid": 500, "tourid": 77},
            ],
        }
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/songs.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_songs_sample.json").read_text(),
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/venues.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_venues_sample.json").read_text(),
    )
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=desc",
        text=two_shows,
    )
    # First show's setlist succeeds
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showid/1234567.json?apikey=test-key",
        text=(fixtures_dir / "phishnet_setlist_show1234567.json").read_text(),
    )
    # Second show's setlist fails with a 503
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showid/1234568.json?apikey=test-key",
        status_code=503,
    )

    conn = open_db(tmp_path / "test.db")
    with PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5") as client:
        stats = run_full_ingest(conn, client)

    # Both shows were processed (ingest didn't abort)
    assert stats["shows"] == 2
    # Only the successful setlist rows were inserted
    assert conn.execute("SELECT count(*) FROM setlist_songs").fetchone()[0] == 2
