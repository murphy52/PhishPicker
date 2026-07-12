"""Phase 5: finalize a show's scorecard (persisted, idempotent) and the
cross-show "best yet?" context."""

from phishpicker.live import append_song, create_live_show
from phishpicker.scoring_service import finalize_scorecard, list_scorecards
from phishpicker.scoring_store import append_snapshot, upsert_score_state


def _seed_show(live_conn, show_date, songs, bracket=(), snapshots=()):
    show_id = create_live_show(live_conn, show_date, venue_id=1597)
    for sid in songs:
        append_song(live_conn, show_id, song_id=sid, set_number="1")
    upsert_score_state(
        live_conn, show_id, model_sha="test-sha", frozen_bracket=list(bracket)
    )
    for snap in snapshots:
        append_snapshot(live_conn, show_id, snap)
    return show_id


BRACKET = [{"set_number": "1", "position": 1, "song_id": 100}]
SNAPS = [
    {
        "after_count": 1,
        "remaining": [{"set_number": "1", "position": 2, "song_id": 101}],
    }
]


def test_finalize_persists_scorecard(seeded_read_db, live_conn):
    show_id = _seed_show(
        live_conn, "2026-04-23", [100, 101], bracket=BRACKET, snapshots=SNAPS
    )
    out = finalize_scorecard(seeded_read_db, live_conn, show_id)
    card = out["scorecard"]
    # opener 100 + live next-song 30
    assert card["combined"] == 130
    assert card["foresight_total"] == 100
    assert card["live_total"] == 30
    assert card["max_streak"] == 1
    assert card["show_date"] == "2026-04-23"
    row = live_conn.execute(
        "SELECT combined FROM scorecards WHERE show_id = ?", (show_id,)
    ).fetchone()
    assert row["combined"] == 130


def test_finalize_is_idempotent_and_refreshes(seeded_read_db, live_conn):
    show_id = _seed_show(
        live_conn, "2026-04-23", [100, 101], bracket=BRACKET, snapshots=SNAPS
    )
    finalize_scorecard(seeded_read_db, live_conn, show_id)
    # A late correction lands; re-finalizing overwrites, no duplicate row.
    append_song(live_conn, show_id, song_id=102, set_number="1")
    out = finalize_scorecard(seeded_read_db, live_conn, show_id)
    n = live_conn.execute("SELECT COUNT(*) FROM scorecards").fetchone()[0]
    assert n == 1
    assert out["scorecard"]["combined"] == 130  # 102 was a miss, no change


def test_best_yet_context(seeded_read_db, live_conn):
    a = _seed_show(
        live_conn, "2026-04-21", [100, 101], bracket=BRACKET, snapshots=SNAPS
    )
    finalize_scorecard(seeded_read_db, live_conn, a)  # 130 pts
    b = _seed_show(live_conn, "2026-04-22", [102])  # nothing banked
    out = finalize_scorecard(seeded_read_db, live_conn, b)
    ctx = out["context"]
    assert ctx["shows_scored"] == 2
    assert ctx["best_total"] == 130
    assert ctx["rank_by_total"] == 2
    assert ctx["is_best"] is False

    cards = list_scorecards(live_conn)
    assert [c["show_date"] for c in cards] == ["2026-04-22", "2026-04-21"]
    assert cards[1]["combined"] == 130


def test_scorecard_endpoints(seeded_client, live_show_id):
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    r = seeded_client.post(f"/live/show/{live_show_id}/scorecard")
    assert r.status_code == 200
    body = r.json()
    assert body["scorecard"]["show_id"] == live_show_id
    assert body["context"]["shows_scored"] == 1
    assert "attributions" in body["result"]

    lst = seeded_client.get("/scorecards")
    assert lst.status_code == 200
    assert len(lst.json()["scorecards"]) == 1

    assert seeded_client.post("/live/show/nope/scorecard").status_code == 404
