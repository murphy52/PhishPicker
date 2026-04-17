def test_songs_endpoint(seeded_client):
    r = seeded_client.get("/songs")
    assert r.status_code == 200
    assert any(s["name"] == "Chalk Dust Torture" for s in r.json())
