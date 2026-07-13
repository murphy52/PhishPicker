"""Streak/combo (Task 1.5): counts consecutive correct next-song calls
regardless of ledger; multiplies only Live-banked points; caps at x2; a wrong
call resets; a missing capture is a no-event (streak unchanged)."""

from phishpicker.scoring import apply_combo, resolve_claims, score_foresight, score_live


def _row(set_number, position, song_id):
    return {"set_number": set_number, "position": position, "song_id": song_id}


ACTUAL = [_row("1", p, sid) for p, sid in enumerate([10, 20, 30, 40, 50, 60, 70], 1)]
# Bracket foresaw song 40 exactly at ("1",4) -> actual index 3 banks Foresight 40.
CALLS = {1: 20, 2: 30, 3: 40, 4: 50, 5: 999, 6: 70}


def _attributions(calls, bracket=()):
    foresight, _ = score_foresight(list(bracket), ACTUAL)
    live = score_live(ACTUAL, calls)
    return apply_combo(ACTUAL, resolve_claims(foresight, live, ACTUAL), calls)


def test_full_timeline():
    atts = _attributions(CALLS, bracket=[_row("1", 4, 40)])
    got = [(a["ledger"], a["streak"], a["final"]) for a in atts]
    assert got == [
        (None, 0, 0),           # opener: never a live event
        ("live", 1, 30),        # 1st in a row, x1
        ("live", 2, 45),        # 2nd, x1.5
        ("foresight", 3, 80),   # streak advances but Foresight never multiplied
        ("live", 4, 60),        # x2 (cap) pays on the Live-banked call
        (None, 0, 0),           # wrong call: streak resets, nothing banked
        ("live", 1, 30),        # streak restarts at x1
    ]


def test_missing_capture_is_no_event():
    # Right call at i1, no capture at i2, right call at i3: the hole must
    # neither advance nor reset the streak.
    calls = {1: 20, 3: 40}
    atts = _attributions(calls)
    assert atts[1]["streak"] == 1 and atts[1]["final"] == 30
    assert atts[2]["called_right"] is None and atts[2]["streak"] == 1
    assert atts[3]["streak"] == 2 and atts[3]["final"] == 45  # x1.5


def test_cap_holds_beyond_third():
    calls = {i: ACTUAL[i]["song_id"] for i in range(1, 7)}
    atts = _attributions(calls)
    assert [a["final"] for a in atts[1:]] == [30, 45, 60, 60, 60, 60]


def test_index_zero_call_ignored():
    atts = _attributions({0: 10, 1: 20})
    assert atts[0]["called_right"] is None
    assert atts[0]["streak"] == 0
    assert atts[1]["streak"] == 1  # i0 contributed nothing to the streak


# --- Foresight combo: consecutive exact-tier hits streak like the live combo ---


def test_foresight_combo_rewards_consecutive_exacts():
    # Bracket nails ("1",2)=20 and ("1",3)=30 -> back-to-back exacts at
    # actual indices 1,2. No live calls.
    atts = _attributions({}, bracket=[_row("1", 2, 20), _row("1", 3, 30)])
    # (reason, fs_streak, fs_mult, final)
    got = [(a["reason"], a["fs_streak"], a["fs_mult"], a["final"]) for a in atts]
    assert got[1] == ("exact", 1, 1.0, 80)   # 1st exact: no bonus
    assert got[2] == ("exact", 2, 1.5, 120)  # 2nd consecutive: x1.5
    assert got[0][1] == 0 and got[3][1] == 0  # misses carry no fs_streak


def test_foresight_combo_caps_at_x2():
    atts = _attributions(
        {}, bracket=[_row("1", 1, 10), _row("1", 2, 20), _row("1", 3, 30), _row("1", 4, 40)]
    )
    # ("1",1) is a set opener -> reason "opener" (base 100); the rest exact.
    assert [a["fs_mult"] for a in atts[:4]] == [1.0, 1.5, 2.0, 2.0]  # cap holds
    assert atts[0]["final"] == 100  # opener x1
    assert atts[3]["final"] == 80 * 2.0  # 4th in a row, capped x2


def test_foresight_combo_resets_on_a_gap():
    # Exact at ("1",1) opener, nothing foreseen at ("1",2), exact at ("1",3).
    atts = _attributions({}, bracket=[_row("1", 1, 10), _row("1", 3, 30)])
    assert atts[0]["fs_streak"] == 1
    assert atts[1]["fs_streak"] == 0  # song 20 not an exact -> reset
    assert atts[2]["fs_streak"] == 1  # streak restarts, no bonus
    assert atts[2]["final"] == 80


def test_lone_exact_is_unchanged_by_the_combo():
    # A single exact still scores its flat base (x1.0) — backward compatible.
    atts = _attributions({}, bracket=[_row("1", 3, 30)])
    assert atts[2]["reason"] == "exact"
    assert atts[2]["fs_mult"] == 1.0 and atts[2]["final"] == 80
