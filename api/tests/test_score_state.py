"""Task 2.1: live_score_state round-trips frozen bracket + snapshots JSON."""

from phishpicker.scoring_store import (
    append_snapshot,
    get_score_state,
    upsert_score_state,
)

BRACKET = [{"set_number": "1", "position": 1, "song_id": 10}]


def test_missing_state_is_none(live_conn, seeded_live_show):
    assert get_score_state(live_conn, seeded_live_show) is None


def test_round_trip(live_conn, seeded_live_show):
    upsert_score_state(
        live_conn, seeded_live_show, model_sha="abc123", frozen_bracket=BRACKET
    )
    st = get_score_state(live_conn, seeded_live_show)
    assert st["model_sha"] == "abc123"
    assert st["frozen_bracket"] == BRACKET
    assert st["snapshots"] == []
    assert st["updated_at"] is not None


def test_append_snapshot_preserves_order(live_conn, seeded_live_show):
    upsert_score_state(
        live_conn, seeded_live_show, model_sha="abc123", frozen_bracket=BRACKET
    )
    snap1 = {"after_count": 1, "remaining": [{"set_number": "1", "position": 2, "song_id": 20}]}
    snap2 = {"after_count": 2, "remaining": []}
    append_snapshot(live_conn, seeded_live_show, snap1)
    append_snapshot(live_conn, seeded_live_show, snap2)
    st = get_score_state(live_conn, seeded_live_show)
    assert st["snapshots"] == [snap1, snap2]


def test_append_snapshot_without_state_creates_row(live_conn, seeded_live_show):
    snap = {"after_count": 1, "remaining": []}
    append_snapshot(live_conn, seeded_live_show, snap)
    st = get_score_state(live_conn, seeded_live_show)
    assert st["snapshots"] == [snap]
    assert st["frozen_bracket"] is None
