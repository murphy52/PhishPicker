from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from phishpicker.phishnet.client import PhishNetClient, PhishNetError


@pytest.fixture
def client() -> Iterator[PhishNetClient]:
    with PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5") as c:
        yield c


def test_fetch_all_shows(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_shows_sample.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=desc",
        text=body,
    )
    shows = client.fetch_all_shows()
    assert len(shows) == 1
    assert shows[0]["showid"] == 1234567


def test_fetch_setlist(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_setlist_show1234567.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showid/1234567.json?apikey=test-key",
        text=body,
    )
    setlist = client.fetch_setlist(1234567)
    assert len(setlist) == 2
    assert setlist[1]["trans_mark"] == ">"


def test_fetch_songs(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_songs_sample.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/songs.json?apikey=test-key",
        text=body,
    )
    songs = client.fetch_songs()
    assert len(songs) == 2
    assert songs[0]["songid"] == 100


def test_fetch_venues(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_venues_sample.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/venues.json?apikey=test-key",
        text=body,
    )
    venues = client.fetch_venues()
    assert len(venues) == 1
    assert venues[0]["venueid"] == 500


def test_http_error_wrapped_as_phishnet_error(client: PhishNetClient, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/songs.json?apikey=test-key",
        status_code=503,
    )
    with pytest.raises(PhishNetError, match="HTTP 503"):
        client.fetch_songs()


def test_request_error_wrapped_as_phishnet_error(client: PhishNetClient, httpx_mock: HTTPXMock):
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url="https://api.phish.net/v5/songs.json?apikey=test-key",
    )
    with pytest.raises(PhishNetError, match="Request failed"):
        client.fetch_songs()
