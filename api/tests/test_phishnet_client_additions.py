from pytest_httpx import HTTPXMock

from phishpicker.phishnet.client import PhishNetClient


def test_fetch_upcoming_shows_filters_by_date_and_phish(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=k&order_by=showdate",
        json={
            "data": [
                {
                    "showid": 1,
                    "showdate": "2026-01-01",
                    "artist_name": "Phish",
                    "venue": "V",
                    "city": "C",
                    "state": "S",
                },
                {
                    "showid": 2,
                    "showdate": "2026-04-23",
                    "artist_name": "Phish",
                    "venue": "Sphere",
                    "city": "Las Vegas",
                    "state": "NV",
                },
                {
                    "showid": 3,
                    "showdate": "2026-04-24",
                    "artist_name": "TAB",
                    "venue": "x",
                    "city": "x",
                    "state": "x",
                },
            ]
        },
    )
    with PhishNetClient(api_key="k") as c:
        shows = c.fetch_upcoming_shows(from_date="2026-04-20")
    assert [s["showid"] for s in shows] == [2]


def test_fetch_upcoming_shows_sorts_ascending_even_when_api_returns_desc(
    httpx_mock: HTTPXMock,
):
    """Regression: phish.net v5 ignores direction=asc and always returns
    newest-first. We must sort in Python so shows[0] is the NEXT show."""
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=k&order_by=showdate",
        json={
            "data": [
                {"showid": 10, "showdate": "2027-01-30", "artist_name": "Phish"},
                {"showid": 20, "showdate": "2026-09-04", "artist_name": "Phish"},
                {"showid": 30, "showdate": "2026-04-23", "artist_name": "Phish"},
            ]
        },
    )
    with PhishNetClient(api_key="k") as c:
        shows = c.fetch_upcoming_shows(from_date="2026-04-20")
    assert [s["showid"] for s in shows] == [30, 20, 10]


def test_fetch_setlist_by_date_filters_to_phish(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {
                    "songid": 1,
                    "song": "Buried Alive",
                    "set": "1",
                    "position": 1,
                    "artist_name": "Phish",
                },
                {
                    "songid": 99,
                    "song": "Other",
                    "set": "1",
                    "position": 1,
                    "artist_name": "TAB",
                },
            ]
        },
    )
    with PhishNetClient(api_key="k") as c:
        rows = c.fetch_setlist_by_date("2026-04-23")
    assert len(rows) == 1
    assert rows[0]["song"] == "Buried Alive"
