"""Task 2.3: capture-don't-recompute — every prediction-changing event
(append, correction, set advance) appends the full remaining prediction to
live_score_state.snapshots. Scoring never re-runs the model."""

from pytest_httpx import HTTPXMock

from phishpicker.db.connection import open_db
from phishpicker.live_sync import sync_show_with_phishnet
from phishpicker.model.scorer import HeuristicScorer
from phishpicker.scoring_store import (
    capture_snapshot,
    get_score_state,
    upsert_score_state,
)


def test_capture_is_cheap_no_build_preview(
    seeded_read_db, live_conn, seeded_live_show, monkeypatch
):
    """Capture must be cheap: a single next-song prediction, NOT the full
    18-slot build_preview (which dominated the write-path latency). Proven by
    making build_preview blow up and asserting capture still succeeds."""
    import phishpicker.scoring_store as store
    from phishpicker.live import append_song
    from phishpicker.model.scorer import HeuristicScorer

    def _boom(*a, **k):
        raise AssertionError("capture must not call build_preview")

    monkeypatch.setattr(store, "_remaining_prediction", _boom)

    scorer = HeuristicScorer()
    upsert_score_state(
        live_conn, seeded_live_show, model_sha=scorer.sha, frozen_bracket=[]
    )
    append_song(live_conn, seeded_live_show, song_id=100, set_number="1")
    assert capture_snapshot(seeded_read_db, live_conn, seeded_live_show, scorer=scorer)
    remaining = get_score_state(live_conn, seeded_live_show)["snapshots"][0]["remaining"]
    assert len(remaining) == 1  # only the immediate next-song call
    assert remaining[0]["set_number"] == "1"
    assert remaining[0]["position"] == 2  # slot after the entered opener


def test_manual_appends_capture_snapshots(seeded_client, live_show_id, tmp_path):
    for song_id in (100, 101):
        r = seeded_client.post(
            "/live/song",
            json={"show_id": live_show_id, "song_id": song_id, "set_number": "1"},
        )
        assert r.status_code == 200
    with open_db(tmp_path / "live.db") as live:
        st = get_score_state(live, live_show_id)
    assert [s["after_count"] for s in st["snapshots"]] == [1, 2]
    # Each snapshot's first remaining entry IS the live next-song call.
    first = st["snapshots"][0]["remaining"][0]
    assert (first["set_number"], first["position"]) == ("1", 2)
    assert isinstance(first["song_id"], int)


def test_advance_set_captures_snapshot(seeded_client, live_show_id, tmp_path):
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    r = seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    assert r.status_code == 200
    with open_db(tmp_path / "live.db") as live:
        st = get_score_state(live, live_show_id)
    # Duplicate after_count is expected — last-appended wins at read time.
    assert [s["after_count"] for s in st["snapshots"]] == [1, 1]
    post_advance = st["snapshots"][-1]["remaining"][0]
    assert post_advance["set_number"] == "2"  # the call moved to the new set


def test_sha_mismatch_skips_capture(seeded_read_db, live_conn, seeded_live_show):
    upsert_score_state(
        live_conn, seeded_live_show, model_sha="someone-else", frozen_bracket=[]
    )
    assert not capture_snapshot(
        seeded_read_db, live_conn, seeded_live_show, scorer=HeuristicScorer()
    )
    assert get_score_state(live_conn, seeded_live_show)["snapshots"] == []


def test_sync_freezes_and_captures(httpx_mock: HTTPXMock, live_setup):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {"songid": 100, "song": "Chalk Dust Torture", "set": "1", "position": 1, "artist_name": "Phish"},
                {"songid": 101, "song": "Tweezer", "set": "1", "position": 2, "artist_name": "Phish"},
            ]
        },
    )
    result = sync_show_with_phishnet(
        db_path=live_setup.db_path,
        live_db_path=live_setup.live_db_path,
        api_key="k",
        show_id=live_setup.show_id,
        show_date="2026-04-23",
        scorer=HeuristicScorer(),
    )
    assert result["appended"] == 2
    with open_db(live_setup.live_db_path) as live:
        st = get_score_state(live, live_setup.show_id)
    # Frozen BEFORE the first sync append — opener slot present.
    slots = {(b["set_number"], b["position"]) for b in st["frozen_bracket"]}
    assert ("1", 1) in slots
    assert [s["after_count"] for s in st["snapshots"]] == [1, 2]
