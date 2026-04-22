def test_post_predict_returns_top_k_from_played(seeded_client):
    r = seeded_client.post(
        "/predict",
        json={
            "played_songs": [],
            "current_set": "1",
            "show_date": "2026-04-23",
            "venue_id": 1597,
            "top_n": 5,
        },
    )
    assert r.status_code == 200
    data = r.json()["candidates"]
    assert len(data) <= 5


def test_post_predict_excludes_played(seeded_client):
    first = seeded_client.post(
        "/predict",
        json={
            "played_songs": [],
            "current_set": "1",
            "show_date": "2026-04-23",
            "venue_id": 1597,
            "top_n": 3,
        },
    ).json()["candidates"]
    assert first, "seed data should produce at least one candidate"
    top_id = first[0]["song_id"]
    second = seeded_client.post(
        "/predict",
        json={
            "played_songs": [top_id],
            "current_set": "1",
            "show_date": "2026-04-23",
            "venue_id": 1597,
            "top_n": 3,
            "prev_set_number": "1",
        },
    ).json()["candidates"]
    assert top_id not in [c["song_id"] for c in second]
