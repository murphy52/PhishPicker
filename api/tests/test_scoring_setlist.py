from phishpicker.scoring import normalize_setlist


def test_normalize_filters_soundcheck_and_sorts():
    rows = [
        {"set_number": "S", "position": 1, "song_id": 99},
        {"set_number": "E", "position": 1, "song_id": 5},
        {"set_number": "1", "position": 2, "song_id": 2},
        {"set_number": "1", "position": 1, "song_id": 1},
    ]
    out = normalize_setlist(rows)
    assert [(r["set_number"], r["position"], r["song_id"]) for r in out] == [
        ("1", 1, 1),
        ("1", 2, 2),
        ("E", 1, 5),
    ]  # 'S' dropped; ordered by set then position


def test_normalize_orders_multi_encore_after_e():
    rows = [
        {"set_number": "E2", "position": 1, "song_id": 8},
        {"set_number": "E", "position": 1, "song_id": 7},
        {"set_number": "2", "position": 1, "song_id": 6},
    ]
    out = normalize_setlist(rows)
    assert [r["song_id"] for r in out] == [6, 7, 8]
