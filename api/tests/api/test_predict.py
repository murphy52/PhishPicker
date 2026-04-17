def test_predict_returns_ranked_candidates(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    r = seeded_client.get(f"/predict/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert "candidates" in body
    assert len(body["candidates"]) >= 1
    # sorted descending by score
    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_predict_excludes_played_tonight(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    seeded_client.post("/live/song", json={"show_id": sid, "song_id": 100, "set_number": "1"})
    r = seeded_client.get(f"/predict/{sid}")
    assert r.status_code == 200
    assert all(c["song_id"] != 100 for c in r.json()["candidates"])


def test_predict_unknown_show_returns_empty(seeded_client):
    r = seeded_client.get("/predict/nonexistent-show-id")
    assert r.status_code == 200
    assert r.json()["candidates"] == []


def test_predict_top_n_limits_results(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    r = seeded_client.get(f"/predict/{sid}?top_n=1")
    assert r.status_code == 200
    assert len(r.json()["candidates"]) == 1


def test_predict_probabilities_sum_to_one(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    candidates = seeded_client.get(f"/predict/{sid}").json()["candidates"]
    assert len(candidates) > 0
    total = sum(c["probability"] for c in candidates)
    assert abs(total - 1.0) < 1e-9


def test_predict_position_resets_for_new_set(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    # Add song 100 in set 1, then advance to set 2 — position in set 2 should be 1 (opener)
    seeded_client.post("/live/song", json={"show_id": sid, "song_id": 100, "set_number": "1"})
    seeded_client.post("/live/set-boundary", json={"show_id": sid, "set_number": "2"})
    r = seeded_client.get(f"/predict/{sid}")
    assert r.status_code == 200
    # Set 2 position 1 means opener logic doesn't apply (current_set="2"), middle logic does
    candidates = r.json()["candidates"]
    assert len(candidates) >= 1
    assert all(c["song_id"] != 100 for c in candidates)
