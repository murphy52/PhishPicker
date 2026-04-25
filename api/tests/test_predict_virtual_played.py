from phishpicker.predict import predict_next_stateless


def test_predict_next_accepts_virtual_played(seeded_read_db):
    """When played_songs is passed explicitly, live DB lookup is bypassed."""
    result = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number=None,
        top_n=5,
    )
    assert len(result) <= 5
    assert all("song_id" in r and "name" in r for r in result)


def test_predict_next_virtual_excludes_previously_played(seeded_read_db):
    first = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number=None,
        top_n=3,
    )
    assert first, "seed data should produce at least one candidate"
    top_id = first[0]["song_id"]
    second = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[top_id],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number="1",
        top_n=3,
    )
    assert top_id not in [r["song_id"] for r in second]


def test_predict_next_stateless_excludes_played_in_run(seeded_read_db):
    """played_in_run songs must be filtered out of the candidate list."""
    baseline = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number=None,
        top_n=5,
    )
    assert baseline, "expected at least one candidate"
    target = baseline[0]["song_id"]

    filtered = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number=None,
        top_n=5,
        played_in_run={target},
    )
    ids = [c["song_id"] for c in filtered]
    assert target not in ids
