from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from phishpicker.phishnet.client import PhishNetClient


@pytest.fixture
def client() -> PhishNetClient:
    return PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5")


def test_fetch_shows_since(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_shows_sample.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=desc",
        text=body,
    )
    shows = client.fetch_shows_since("1900-01-01")
    assert len(shows) == 1
    assert shows[0]["showid"] == 1234567


def test_fetch_setlist(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_setlist_show1234567.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/get.json?apikey=test-key&showid=1234567",
        text=body,
    )
    setlist = client.fetch_setlist(1234567)
    assert len(setlist) == 2
    assert setlist[1]["trans_mark"] == ">"
