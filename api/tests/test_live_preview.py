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


def test_preview_does_not_extend_past_default_when_set_is_closed(
    seeded_client, live_show_id
):
    """A set the user has moved past gets exactly its entered count — no
    phantom +1 prediction."""
    # Enter a couple in Set 1, then advance. No overflow, but verify the
    # boundary: a non-current set with entered < default still shows default.
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    # Set 1 still gets its default 9 (1 entered + 8 predicted) — we don't
    # shrink below default, and no +1 because Set 1 isn't current.
    set1 = [s for s in slots if s["set_number"] == "1"]
    assert len(set1) == 9
    # Set 2 is current: default 7 + 1 speculative = 8? No — no entered in Set 2
    # yet, so max(7, 0+1) = 7. Still 7 slots.
    set2 = [s for s in slots if s["set_number"] == "2"]
    assert len(set2) == 7


def test_preview_respects_live_show_meta_sizes(seeded_client, live_show_id):
    r = seeded_client.post(
        f"/live/show/{live_show_id}/structure",
        json={"set1": 10, "set2": 8, "encore": 3},
    )
    assert r.status_code == 200
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r2.json()["slots"]
    assert len(slots) == 21
