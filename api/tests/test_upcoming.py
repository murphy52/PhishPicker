from pytest_httpx import HTTPXMock


def test_upcoming_returns_next_phish_with_tz(
    httpx_mock: HTTPXMock, seeded_client
):
    httpx_mock.add_response(
        url=(
            "https://api.phish.net/v5/shows.json"
            "?apikey=test-key&order_by=showdate"
        ),
        json={
            "data": [
                {
                    "showid": 2,
                    "showdate": "2026-04-23",
                    "artist_name": "Phish",
                    "venue": "Sphere",
                    "city": "Las Vegas",
                    "state": "NV",
                },
            ]
        },
    )
    r = seeded_client.get("/upcoming")
    assert r.status_code == 200
    assert r.json() == {
        "show_id": 2,
        "show_date": "2026-04-23",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
        "timezone": "America/Los_Angeles",
        "start_time_local": "19:00",
    }


def test_upcoming_404s_when_no_future_shows(httpx_mock: HTTPXMock, seeded_client):
    httpx_mock.add_response(
        url=(
            "https://api.phish.net/v5/shows.json"
            "?apikey=test-key&order_by=showdate"
        ),
        json={"data": []},
    )
    r = seeded_client.get("/upcoming")
    assert r.status_code == 404
