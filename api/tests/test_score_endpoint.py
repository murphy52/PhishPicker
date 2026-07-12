"""Task 3.1: recompute-on-read scoring — scoring_service derives the engine
inputs from live_songs + live_score_state and GET /live/show/{id}/score
returns the result. Task 3.2: corrections re-score cleanly."""

from phishpicker.live import append_song, create_live_show, replace_song_at
from phishpicker.scoring_service import score_live_show
from phishpicker.scoring_store import append_snapshot, upsert_score_state


def _snap(after_count, *entries):
    return {
        "after_count": after_count,
        "remaining": [
            {"set_number": s, "position": p, "song_id": sid} for s, p, sid in entries
        ],
    }


def _seed_show(live_conn):
    """4 songs in set 1. Bracket foresaw the opener exactly. Captured calls:
    i1 right (after a stale duplicate — last-wins), i2 wrong, i3 wrong but
    placed 2+ slots ahead in an early snapshot (badge)."""
    show_id = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    for sid in (100, 101, 102, 103):
        append_song(live_conn, show_id, song_id=sid, set_number="1")
    upsert_score_state(
        live_conn,
        show_id,
        model_sha="test-sha",
        frozen_bracket=[{"set_number": "1", "position": 1, "song_id": 100}],
    )
    append_snapshot(live_conn, show_id, _snap(1, ("1", 2, 999), ("1", 4, 103)))
    append_snapshot(live_conn, show_id, _snap(1, ("1", 2, 101), ("1", 4, 103)))
    append_snapshot(live_conn, show_id, _snap(2, ("1", 3, 999)))
    append_snapshot(live_conn, show_id, _snap(3, ("1", 4, 888)))
    return show_id


def test_score_live_show_derivations(seeded_read_db, live_conn):
    show_id = _seed_show(live_conn)
    result = score_live_show(seeded_read_db, live_conn, show_id)
    atts = result["attributions"]

    assert [(a["ledger"], a["final"], a["streak"]) for a in atts] == [
        ("foresight", 100, 0),  # opener exact + bonus
        ("live", 30, 1),       # last-wins: the corrected snapshot called 101
        (None, 0, 0),          # wrong call -> miss, streak resets
        (None, 0, 0),          # wrong call
    ]
    assert atts[2]["missed"] is True and atts[2]["bustout"] is False
    # 103 was correctly placed at ("1",4) in the after_count=1 snapshot,
    # 2+ slots ahead of its reveal at index 3.
    assert atts[3]["called_early"] is True

    totals = result["totals"]
    assert totals["foresight_total"] == 100
    assert totals["live_total"] == 30
    assert totals["combined"] == 130
    assert totals["ppps"] == 130 / 4
    assert result["model_sha"] == "test-sha"


def test_bustout_placeholder_flagged(seeded_read_db, live_conn):
    seeded_read_db.execute(
        "INSERT INTO songs (song_id, name, first_seen_at, is_bustout_placeholder) "
        "VALUES (900, 'Icculus', '2026-04-23', 1)"
    )
    seeded_read_db.commit()
    show_id = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    for sid in (100, 900):
        append_song(live_conn, show_id, song_id=sid, set_number="1")
    upsert_score_state(live_conn, show_id, model_sha="test-sha", frozen_bracket=[])
    result = score_live_show(seeded_read_db, live_conn, show_id)
    assert result["attributions"][1]["bustout"] is True
    assert result["totals"]["ppps"] == 0  # 0 points / 1 predictable song


def test_correction_rescores_cleanly(seeded_read_db, live_conn):
    """Task 3.2: a phish.net correction (replace + fresh snapshot) changes the
    score by exactly the corrected song's claim delta — no extra code."""
    show_id = _seed_show(live_conn)
    before = score_live_show(seeded_read_db, live_conn, show_id)
    assert before["totals"]["combined"] == 130

    # phish.net says the 2nd song was actually 105, and the model's call for
    # the NEXT reveal (i4, not yet played) refreshes — same after_count as
    # a later entry would produce; harmless.
    replace_song_at(live_conn, show_id, entered_order=2, new_song_id=105)
    append_snapshot(live_conn, show_id, _snap(4, ("1", 5, 555)))

    after = score_live_show(seeded_read_db, live_conn, show_id)
    # The i1 live hit (30) is gone — its captured call said 101, but the
    # corrected setlist says 105 played. Everything else is untouched.
    assert after["totals"]["combined"] == 100
    assert after["attributions"][1]["ledger"] is None
    assert after["attributions"][0]["final"] == 100


def test_score_endpoint_smoke(seeded_client, live_show_id):
    for sid in (100, 101):
        seeded_client.post(
            "/live/song",
            json={"show_id": live_show_id, "song_id": sid, "set_number": "1"},
        )
    r = seeded_client.get(f"/live/show/{live_show_id}/score")
    assert r.status_code == 200
    body = r.json()
    assert len(body["attributions"]) == 2
    assert set(body["totals"]) >= {"foresight_total", "live_total", "combined", "ppps"}
    # Names enriched for the UI
    assert body["attributions"][0]["name"] == "Chalk Dust Torture"


def test_score_endpoint_404(seeded_client):
    assert seeded_client.get("/live/show/nope/score").status_code == 404


def test_pick_outcomes_carry_names_including_absent(seeded_read_db, live_conn):
    """The predicted-setlist view renders the frozen bracket, so every pick —
    including 'absent' ones that never played — needs a song name. Names must
    be resolved for the whole bracket, not just the actual setlist."""
    show_id = create_live_show(live_conn, "2026-04-23", venue_id=1597)
    append_song(live_conn, show_id, song_id=100, set_number="1")  # Chalk Dust plays
    upsert_score_state(
        live_conn,
        show_id,
        model_sha="test-sha",
        frozen_bracket=[
            {"set_number": "1", "position": 1, "song_id": 100},  # exact opener
            {"set_number": "1", "position": 2, "song_id": 101},  # predicted, never played
        ],
    )
    result = score_live_show(seeded_read_db, live_conn, show_id)
    by_song = {o["pick"]["song_id"]: o for o in result["pick_outcomes"]}
    assert by_song[100]["name"] == "Chalk Dust Torture"
    assert by_song[100]["reason"] == "opener"
    # The absent pick still carries its name for the predicted-setlist page.
    assert by_song[101]["name"] == "Tweezer"
    assert by_song[101]["reason"] == "absent"


def test_score_exposes_show_meta(seeded_read_db, live_conn):
    """The scoreboard + bracket header read venue/date/city/run from the
    score payload's `show` block, resolved from (show_date, venue_id)."""
    show_id = create_live_show(live_conn, "2024-07-21", venue_id=500)
    append_song(live_conn, show_id, song_id=100, set_number="1")
    result = score_live_show(seeded_read_db, live_conn, show_id)
    meta = result["show"]
    assert meta["show_date"] == "2024-07-21"
    assert meta["venue"] == "Madison Square Garden"
    assert meta["city"] == "New York"
    assert meta["state"] == "NY"
    # The lone fixture show at this venue -> a one-off, no residency badge.
    assert meta["run_length"] is None


def test_score_endpoint_exposes_named_bracket(seeded_client, live_show_id):
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    body = seeded_client.get(f"/live/show/{live_show_id}/score").json()
    assert body["frozen"] is True
    assert body["pick_outcomes"], "a started show has a frozen bracket"
    assert all("name" in o for o in body["pick_outcomes"])
