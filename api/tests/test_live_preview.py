def test_preview_default_972_structure(seeded_client, live_show_id):
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert len(slots) == 18
    sets = [s["set_number"] for s in slots]
    assert sets.count("1") == 9
    assert sets.count("2") == 7
    assert sets.count("E") == 2


def test_preview_marks_entered_slots(seeded_client, live_show_with_one_song):
    r = seeded_client.get(
        f"/live/show/{live_show_with_one_song['show_id']}/preview"
    )
    slots = r.json()["slots"]
    assert slots[0]["state"] == "entered"
    assert slots[0]["entered_song"]["song_id"] == live_show_with_one_song["song_id"]
    assert slots[1]["state"] == "predicted"


def test_preview_predicted_slot_has_top_k(seeded_client, live_show_id):
    r = seeded_client.get(f"/live/show/{live_show_id}/preview?top_k=10")
    slots = r.json()["slots"]
    predicted = [s for s in slots if s["state"] == "predicted"]
    assert predicted, "expected at least one predicted slot"
    # Some slots may have <10 candidates if the seed pool is small; but >=1.
    for s in predicted:
        assert "top_k" in s
        assert all("rank" in c for c in s["top_k"])


def test_preview_extends_past_default_when_current_set_overflows(
    seeded_client, live_show_id
):
    """If Set 1 has more entered rows than the default (9), the preview must
    show every entered song plus one speculative set-closer prediction."""
    # Seed 10 songs into Set 1 (one past the default).
    for song_id in range(100, 110):
        r = seeded_client.post(
            "/live/song",
            json={"show_id": live_show_id, "song_id": song_id, "set_number": "1"},
        )
        assert r.status_code == 200

    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    set1 = [s for s in slots if s["set_number"] == "1"]
    # 10 entered + 1 speculative = 11
    assert len(set1) == 11
    assert all(s["state"] == "entered" for s in set1[:10])
    assert set1[10]["state"] == "predicted"


def test_preview_shrinks_past_set_to_entered_count(seeded_client, live_show_id):
    """Once a set is in the past (user advanced), its slot count collapses
    to exactly what the user entered — unused predictions vanish."""
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    set1 = [s for s in slots if s["set_number"] == "1"]
    # Set 1 is past — exactly 1 entered, no phantom predictions.
    assert len(set1) == 1
    assert set1[0]["state"] == "entered"
    # Set 2 is active, no entered yet — default 7 (max(7, 0+1) = 7).
    set2 = [s for s in slots if s["set_number"] == "2"]
    assert len(set2) == 7


def test_preview_hides_past_set_with_no_entered(seeded_client, live_show_id):
    """Advancing without entering anything in Set 1 hides Set 1 entirely."""
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    assert not [s for s in slots if s["set_number"] == "1"]


def test_preview_restores_predictions_when_walking_back_to_set(
    seeded_client, live_show_id
):
    """If the user walks back via /set-boundary, the predicted slots return
    up to the default."""
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    assert len([s for s in r.json()["slots"] if s["set_number"] == "1"]) == 1

    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "1"}
    )
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    set1 = [s for s in r2.json()["slots"] if s["set_number"] == "1"]
    assert len(set1) == 9
    assert set1[0]["state"] == "entered"
    assert all(s["state"] == "predicted" for s in set1[1:])


def test_preview_respects_live_show_meta_sizes(seeded_client, live_show_id):
    r = seeded_client.post(
        f"/live/show/{live_show_id}/structure",
        json={"set1": 10, "set2": 8, "encore": 3},
    )
    assert r.status_code == 200
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r2.json()["slots"]
    assert len(slots) == 21
