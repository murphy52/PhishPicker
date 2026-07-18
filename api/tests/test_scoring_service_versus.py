"""Task 2: score_live_show attaches a `versus` (Phish vs PhishPicker) block
when a bracket is frozen, and _surprise_weights tiers absent-song band bonuses
bustout > deep-cut > common."""

from phishpicker.live import append_song
from phishpicker.scoring import (
    VS_BAND_BUSTOUT_BONUS,
    VS_BAND_RARE_BONUS,
)
from phishpicker.scoring_service import _surprise_weights, score_live_show
from phishpicker.scoring_store import upsert_score_state


def test_versus_attached_when_bracket_frozen(seeded_read_db, live_conn, seeded_live_show):
    show_id = seeded_live_show
    # Freeze a bracket that predicts song 100 as the set-1 opener. Song 101 is
    # NOT in the bracket, so when it's played it scores for the band.
    upsert_score_state(
        live_conn,
        show_id,
        model_sha="test-sha",
        frozen_bracket=[{"song_id": 100, "set_number": "1", "position": 1}],
    )
    # Multi-set setlist: 100 opens set 1 (a bracket pick), 101 opens set 2 (absent).
    append_song(live_conn, show_id, song_id=100, set_number="1")
    append_song(live_conn, show_id, song_id=101, set_number="2")

    result = score_live_show(seeded_read_db, live_conn, show_id)

    assert "versus" in result
    v = result["versus"]
    assert set(v) == {"picker_total", "phish_total", "leader", "per_song"}
    assert len(v["per_song"]) == 2  # one entry per entered song
    assert all("name" in ps for ps in v["per_song"])  # names resolved
    assert {ps["side"] for ps in v["per_song"]} <= {"picker", "phish"}

    by_song = {ps["song_id"]: ps for ps in v["per_song"]}
    assert by_song[100]["side"] == "picker"  # bracket-matching song
    assert by_song[101]["side"] == "phish"  # off-bracket song
    assert by_song[100]["name"] == "Chalk Dust Torture"
    assert by_song[101]["name"] == "Tweezer"


def test_versus_absent_without_frozen_bracket(seeded_read_db, live_conn, seeded_live_show):
    # No score state -> empty bracket -> the vs-game is gated off. Enter a song
    # so the setlist isn't empty; `versus` must still be absent.
    show_id = seeded_live_show
    append_song(live_conn, show_id, song_id=100, set_number="1")

    result = score_live_show(seeded_read_db, live_conn, show_id)

    assert "versus" not in result


def test_surprise_weights_tiers_bustout_then_rare_then_common(seeded_read_db):
    conn = seeded_read_db
    bustout_id, rare_id, common_id = 200, 201, 202
    conn.executemany(
        "INSERT INTO songs (song_id, name, first_seen_at, is_bustout_placeholder) "
        "VALUES (?, ?, '2020-01-01', ?)",
        [
            (bustout_id, "Bustout Placeholder", 1),
            (rare_id, "Rare Deep Cut", 0),
            (common_id, "Common Rotation", 0),
        ],
    )
    # Shows to satisfy the setlist_songs -> shows FK.
    conn.executemany(
        "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
        [(900000, "2020-02-01", "2020-02-01"), (900001, "2020-03-01", "2020-03-01")],
    )
    # Rare: 3 historical plays (< VS_RARE_PLAYS_MAX=50).
    conn.executemany(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
        [(900000, "1", p, rare_id) for p in range(1, 4)],
    )
    # Common: 50 historical plays (>= 50).
    conn.executemany(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
        [(900001, "1", p, common_id) for p in range(1, 51)],
    )
    conn.commit()

    actual = [
        {"song_id": bustout_id, "set_number": "1", "position": 1},
        {"song_id": rare_id, "set_number": "1", "position": 2},
        {"song_id": common_id, "set_number": "1", "position": 3},
    ]
    w = _surprise_weights(conn, actual, bustout_song_ids={bustout_id})
    assert w[bustout_id] == (VS_BAND_BUSTOUT_BONUS, "absent-bustout")
    assert w[rare_id] == (VS_BAND_RARE_BONUS, "absent-rare")
    assert w[common_id] == (0, "absent")
