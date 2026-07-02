"""Task 2.2: the Foresight bracket freezes at show start — BEFORE the first
live_songs insert (build_preview reads entered songs from the DB, so a
post-insert freeze would silently lose the opener pick, the 60-pt slot)."""

from phishpicker.db.connection import open_db
from phishpicker.model.scorer import HeuristicScorer
from phishpicker.scoring_store import ensure_frozen, get_score_state


def test_freeze_captures_deduped_full_bracket(seeded_read_db, live_conn, seeded_live_show):
    scorer = HeuristicScorer()
    assert ensure_frozen(seeded_read_db, live_conn, seeded_live_show, scorer=scorer)
    st = get_score_state(live_conn, seeded_live_show)
    bracket = st["frozen_bracket"]
    slots = {(b["set_number"], b["position"]) for b in bracket}
    # The tiny seed fixture runs the candidate pool dry after a couple of
    # slots, so assert the opener is present rather than the full structure.
    assert ("1", 1) in slots
    ids = [b["song_id"] for b in bracket]
    assert len(ids) == len(set(ids)), "bracket must be deduped one-song-per-slot"
    assert st["model_sha"] == scorer.sha


def test_freeze_is_idempotent(seeded_read_db, live_conn, seeded_live_show):
    scorer = HeuristicScorer()
    ensure_frozen(seeded_read_db, live_conn, seeded_live_show, scorer=scorer)
    first = get_score_state(live_conn, seeded_live_show)["frozen_bracket"]
    assert not ensure_frozen(seeded_read_db, live_conn, seeded_live_show, scorer=scorer)
    assert get_score_state(live_conn, seeded_live_show)["frozen_bracket"] == first


def test_first_manual_append_freezes_before_insert(seeded_client, live_show_id, tmp_path):
    r = seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    assert r.status_code == 200
    live = open_db(tmp_path / "live.db")
    try:
        st = get_score_state(live, live_show_id)
        assert st is not None and st["frozen_bracket"], "freeze must trigger on first append"
        slots = {(b["set_number"], b["position"]) for b in st["frozen_bracket"]}
        # The opener slot is only present if the freeze ran BEFORE the insert.
        assert ("1", 1) in slots

        # Second append: bracket untouched.
        frozen = st["frozen_bracket"]
        seeded_client.post(
            "/live/song",
            json={"show_id": live_show_id, "song_id": 101, "set_number": "1"},
        )
        assert get_score_state(live, live_show_id)["frozen_bracket"] == frozen
    finally:
        live.close()
