def test_post_songs_inserts_bustout(seeded_client):
    r = seeded_client.post("/songs", json={"name": "Mystery Cover"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Mystery Cover"
    assert body["is_bustout_placeholder"] is True
    assert isinstance(body["song_id"], int)


def test_post_songs_idempotent_on_duplicate_name(seeded_client):
    r1 = seeded_client.post("/songs", json={"name": "Brand New Tune"})
    assert r1.status_code == 201
    sid1 = r1.json()["song_id"]
    r2 = seeded_client.post("/songs", json={"name": "Brand New Tune"})
    assert r2.status_code == 200
    assert r2.json()["song_id"] == sid1


def test_post_songs_returns_existing_non_bustout_unchanged(seeded_client):
    """If the name is already a real (non-bustout) song, return it as-is."""
    # 'Chalk Dust Torture' is in the seed fixture (song_id=100, not bustout).
    r = seeded_client.post("/songs", json={"name": "Chalk Dust Torture"})
    assert r.status_code == 200
    body = r.json()
    assert body["song_id"] == 100
    assert body["is_bustout_placeholder"] is False
