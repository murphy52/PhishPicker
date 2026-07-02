"""build_preview must survive a double encore: entered E2 songs render, prior
sets collapse to their entered counts, and exactly one next-song slot exists."""


def _enter(client, show_id, song_id, set_number):
    r = client.post(
        "/live/song",
        json={"show_id": show_id, "song_id": song_id, "set_number": set_number},
    )
    assert r.status_code == 200


def _advance(client, show_id, set_number):
    r = client.post(
        "/live/set-boundary", json={"show_id": show_id, "set_number": set_number}
    )
    assert r.status_code == 200


def test_preview_handles_double_encore(seeded_client, live_show_id):
    _enter(seeded_client, live_show_id, 100, "1")
    _advance(seeded_client, live_show_id, "2")
    _enter(seeded_client, live_show_id, 101, "2")
    _advance(seeded_client, live_show_id, "E")
    _enter(seeded_client, live_show_id, 102, "E")
    _advance(seeded_client, live_show_id, "E2")
    _enter(seeded_client, live_show_id, 103, "E2")

    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    assert r.status_code == 200
    slots = r.json()["slots"]

    # Past sets collapse to exactly their entered rows — no phantom
    # re-opened predicted slots.
    for s, expected_song in [("1", 100), ("2", 101), ("E", 102)]:
        in_set = [x for x in slots if x["set_number"] == s]
        assert len(in_set) == 1, f"set {s} should collapse to 1 entered slot"
        assert in_set[0]["state"] == "entered"
        assert in_set[0]["entered_song"]["song_id"] == expected_song

    # The active E2 set: the entered song plus one speculative next slot.
    e2 = [x for x in slots if x["set_number"] == "E2"]
    assert [x["state"] for x in e2] == ["entered", "predicted"]
    assert e2[0]["entered_song"]["song_id"] == 103
    # The entered E2 song joined virtual_played — it can't be predicted again.
    assert all(c["song_id"] != 103 for c in e2[1]["top_k"])
