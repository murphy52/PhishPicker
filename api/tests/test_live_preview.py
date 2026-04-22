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


def test_preview_respects_live_show_meta_sizes(seeded_client, live_show_id):
    r = seeded_client.post(
        f"/live/show/{live_show_id}/structure",
        json={"set1": 10, "set2": 8, "encore": 3},
    )
    assert r.status_code == 200
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r2.json()["slots"]
    assert len(slots) == 21
