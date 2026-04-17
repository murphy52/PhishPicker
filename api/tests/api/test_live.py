def test_create_live_show(seeded_client):
    r = seeded_client.post("/live/show", json={"show_date": "2024-08-01", "venue_id": 500})
    assert r.status_code == 200
    show_id = r.json()["show_id"]

    r2 = seeded_client.get(f"/live/show/{show_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["show_id"] == show_id
    assert data["show_date"] == "2024-08-01"
    assert data["venue_id"] == 500
    assert data["current_set"] == "1"
    assert data["songs"] == []


def test_append_live_song(seeded_client):
    r = seeded_client.post("/live/show", json={"show_date": "2024-08-02"})
    show_id = r.json()["show_id"]

    r2 = seeded_client.post(
        "/live/song",
        json={"show_id": show_id, "song_id": 100, "set_number": "1"},
    )
    assert r2.status_code == 200
    assert r2.json()["entered_order"] == 1

    r3 = seeded_client.get(f"/live/show/{show_id}")
    assert r3.status_code == 200
    assert len(r3.json()["songs"]) == 1
    assert r3.json()["songs"][0]["song_id"] == 100


def test_undo_last_song(seeded_client):
    r = seeded_client.post("/live/show", json={"show_date": "2024-08-03"})
    show_id = r.json()["show_id"]

    seeded_client.post("/live/song", json={"show_id": show_id, "song_id": 100, "set_number": "1"})
    seeded_client.post("/live/song", json={"show_id": show_id, "song_id": 101, "set_number": "1"})

    r2 = seeded_client.delete(f"/live/song/last?show_id={show_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] is True

    r3 = seeded_client.get(f"/live/show/{show_id}")
    songs = r3.json()["songs"]
    assert len(songs) == 1
    assert songs[0]["song_id"] == 100


def test_set_boundary(seeded_client):
    r = seeded_client.post("/live/show", json={"show_date": "2024-08-04"})
    show_id = r.json()["show_id"]

    r2 = seeded_client.post("/live/set-boundary", json={"show_id": show_id, "set_number": "2"})
    assert r2.status_code == 200
    assert r2.json()["updated"] is True

    r3 = seeded_client.get(f"/live/show/{show_id}")
    assert r3.json()["current_set"] == "2"
