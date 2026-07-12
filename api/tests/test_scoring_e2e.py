"""Task 1.8: the regression anchor — a full hand-built imaginary show run
through score_show, asserting per-song attributions, ledger totals, and the
streak timeline. Based on the design doc's worked example (Tweezer foreseen in
the wrong set, then called live -> Live 30 beats Foresight 5).

Song ids: 1 Chalk Dust, 2 Reba, 3 Ghost, 4 Tweezer, 5 Fluffhead,
6 Loving Cup, 8 Harry Hood (never plays), 99 genuine bustout.
"""

from phishpicker.scoring import score_show


def _row(set_number, position, song_id):
    return {"set_number": set_number, "position": position, "song_id": song_id}


BRACKET = [
    _row("1", 1, 1),   # Chalk Dust opener — plays exactly there -> 100
    _row("1", 2, 2),   # Reba — plays ("1",3) -> right_set 15 (beaten by live 30)
    _row("1", 3, 4),   # Tweezer — plays ("2",1) -> somewhere 5 (beaten by live 30)
    _row("2", 1, 3),   # Ghost — plays ("2",2) -> right_set 15 (beaten by live 30)
    _row("2", 3, 8),   # Harry Hood — never plays -> absent whiff
    _row("E", 1, 6),   # Loving Cup encore opener — exact -> 100
]

ACTUAL = [
    _row("1", 1, 1),    # i0 Chalk Dust
    _row("1", 2, 5),    # i1 Fluffhead (not in bracket, called live)
    _row("1", 3, 2),    # i2 Reba
    _row("2", 1, 4),    # i3 Tweezer
    _row("2", 2, 3),    # i4 Ghost
    _row("2", 3, 99),   # i5 bustout (call was wrong)
    _row("E", 1, 6),    # i6 Loving Cup (no capture — sync gap)
]

CALLS = {1: 5, 2: 2, 3: 4, 4: 3, 5: 7}  # i5 wrong; i6 absent (no capture)


def test_full_show():
    result = score_show(
        BRACKET,
        ACTUAL,
        CALLS,
        early_called_indices={4},
        bustout_song_ids={99},
    )
    atts = result["attributions"]

    # (ledger, final, streak) timeline
    assert [(a["ledger"], a["final"], a["streak"]) for a in atts] == [
        ("foresight", 100, 0),  # opener banked pre-show; live starts after
        ("live", 30, 1),        # Fluffhead called, x1
        ("live", 45, 2),        # Reba called, x1.5 — beat foresight right_set
        ("live", 60, 3),        # Tweezer called, x2 — the design's worked example
        ("live", 60, 4),        # Ghost called, x2 (cap holds)
        (None, 0, 0),           # bustout: wrong call resets the streak
        ("foresight", 100, 0),  # Loving Cup encore opener; no capture = no-event
    ]

    # Beaten claims are recorded for the UI
    assert atts[3]["beaten_claim"] == {
        "ledger": "foresight",
        "reason": "somewhere",
        "base": 5,
    }
    assert atts[2]["beaten_claim"]["reason"] == "right_set"

    # Flags
    assert atts[4]["called_early"] is True
    assert atts[5]["bustout"] is True and atts[5]["missed"] is False

    # Totals
    totals = result["totals"]
    assert totals["foresight_total"] == 200  # two openers at 100
    assert totals["live_total"] == 30 + 45 + 60 + 60
    assert totals["combined"] == 395
    assert totals["ppps"] == 395 / 6  # 7 songs minus 1 bustout
    assert totals["hit_counts"] == {"opener": 2, "next_song": 4}

    # The Hood whiff shows up in pick outcomes for the recap
    whiffs = [o for o in result["pick_outcomes"] if o["reason"] == "absent"]
    assert [o["pick"]["song_id"] for o in whiffs] == [8]
