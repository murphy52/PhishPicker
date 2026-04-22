def test_slot_alternatives_returns_single_slot(seeded_client, live_show_id):
    r = seeded_client.get(
        f"/live/show/{live_show_id}/slot/5/alternatives?top_k=5"
    )
    assert r.status_code == 200
    s = r.json()
    assert s["slot_idx"] == 5
    assert s["state"] == "predicted"
    assert "top_k" in s


def test_slot_alternatives_404_on_out_of_range(seeded_client, live_show_id):
    r = seeded_client.get(
        f"/live/show/{live_show_id}/slot/999/alternatives"
    )
    assert r.status_code == 404


def test_slot_alternatives_returns_entered_slot(
    seeded_client, live_show_with_one_song
):
    r = seeded_client.get(
        f"/live/show/{live_show_with_one_song['show_id']}/slot/1/alternatives"
    )
    assert r.status_code == 200
    s = r.json()
    assert s["state"] == "entered"
    assert s["entered_song"]["song_id"] == live_show_with_one_song["song_id"]
