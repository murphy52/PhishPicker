from phishpicker.scoring import (
    VS_BAND_BASE,
    VS_PICKER,
    score_versus,
)


def _actual(*specs):
    """specs are (song_id, set, position) triples in setlist order."""
    return [{"song_id": s, "set_number": st, "position": p} for s, st, p in specs]


def _bracket(*specs):
    return [{"song_id": s, "set_number": st, "position": p} for s, st, p in specs]


def test_exact_bracket_hit_scores_for_the_picker():
    # NOTE: (1,1)/(2,1)/etc are OPENER slots that score_foresight upgrades to
    # reason "opener" (see OPENER_SLOTS in scoring.py). Use a NON-opener exact
    # slot here so we test the "exact" tier, not the opener tier.
    br = _bracket((100, "1", 2))
    act = _actual((100, "1", 2))
    out = score_versus(br, act, surprise_by_song={})
    assert out["per_song"][0]["side"] == "picker"
    assert out["per_song"][0]["reason"] == "exact"
    assert out["per_song"][0]["points"] == VS_PICKER["exact"]
    assert out["picker_total"] == VS_PICKER["exact"]
    assert out["phish_total"] == 0
    assert out["leader"] == "picker"


def test_opener_slot_hit_scores_the_opener_tier():
    # A pick placed and played at slot (1,1) upgrades exact -> opener.
    br = _bracket((100, "1", 1))
    act = _actual((100, "1", 1))
    out = score_versus(br, act, surprise_by_song={})
    assert out["per_song"][0]["reason"] == "opener"
    assert out["per_song"][0]["points"] == VS_PICKER["opener"]


def test_repeated_song_splits_picker_then_phish():
    # Consume-once: one bracket pick for song 100; played twice. First
    # occurrence claimed (picker), second falls through to phish.
    br = _bracket((100, "1", 2))
    act = _actual((100, "1", 2), (100, "2", 3))
    out = score_versus(br, act, surprise_by_song={100: (2, "absent-rare")})
    assert out["per_song"][0]["side"] == "picker"
    assert out["per_song"][1]["side"] == "phish"
    assert out["per_song"][1]["points"] == VS_BAND_BASE + 2


def test_song_absent_from_bracket_scores_for_phish():
    br = _bracket((100, "1", 1))
    act = _actual((999, "1", 1))  # not in the bracket at all
    out = score_versus(br, act, surprise_by_song={})
    ps = out["per_song"][0]
    assert ps["side"] == "phish"
    assert ps["points"] == VS_BAND_BASE  # no surprise bonus supplied
    assert out["leader"] == "phish"


def test_surprise_bonus_is_added_for_band_songs():
    br = _bracket((100, "1", 1))
    act = _actual((999, "1", 1))
    out = score_versus(br, act, surprise_by_song={999: (8, "absent-bustout")})
    ps = out["per_song"][0]
    assert ps["points"] == VS_BAND_BASE + 8
    assert ps["reason"] == "absent-bustout"


def test_right_set_scores_less_than_exact_but_still_picker():
    # Predicted (2,1), played (2,3): right set, wrong slot.
    br = _bracket((100, "2", 1))
    act = _actual((100, "2", 3))
    out = score_versus(br, act, surprise_by_song={})
    assert out["per_song"][0]["side"] == "picker"
    assert out["per_song"][0]["points"] == VS_PICKER["right_set"]
    assert VS_PICKER["right_set"] < VS_PICKER["exact"]


def test_tie_reports_tie():
    # Non-opener exact pick (banks VS_PICKER["exact"]) + one absent band song
    # weighted to match it exactly. Note (2,3) is not an opener slot.
    br = _bracket((100, "1", 2))
    act = _actual((100, "1", 2), (999, "2", 3))
    out = score_versus(
        br, act, surprise_by_song={999: (VS_PICKER["exact"] - VS_BAND_BASE, "absent")}
    )
    assert out["picker_total"] == out["phish_total"]
    assert out["leader"] == "tie"


def test_direction_matches_the_tour_magic_night():
    """Synthetic magic-night shape: bracket places most songs -> picker wins.
    (This is a sign-flip guard only; the REAL calibration contract is the
    real-data test in Task 6, which uses the actual Jul-12/Jul-14 brackets.)"""
    br = _bracket(*[(i, "1", i) for i in range(1, 9)],
                  *[(i, "2", i - 8) for i in range(9, 16)])
    # 8 played songs hit their exact predicted slots (picker), 7 are absent (band).
    act = _actual(*[(i, "1", i) for i in range(1, 9)],
                  *[(900 + i, "2", i) for i in range(1, 8)])
    out = score_versus(br, act, surprise_by_song={})
    assert out["leader"] == "picker"


def test_direction_matches_the_tour_weird_night():
    """Jul-14 shape: bracket places almost nothing -> band should win."""
    br = _bracket(*[(i, "1", i) for i in range(1, 16)])
    act = _actual(*[(500 + i, "1", i) for i in range(1, 16)])  # all absent
    out = score_versus(br, act, surprise_by_song={})
    assert out["leader"] == "phish"
