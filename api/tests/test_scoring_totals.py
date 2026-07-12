"""Badges/flags (Task 1.6) and totals + points-per-predictable-song (Task 1.7).

Bustout status comes ONLY from the explicit bustout_song_ids input — a plain
whiff (no claim from either ledger) is `missed`, stays in the PPS denominator,
and must never celebrate as a bustout.
"""

from phishpicker.scoring import (
    apply_badges,
    apply_combo,
    resolve_claims,
    score_foresight,
    score_live,
    summarize,
)


def _row(set_number, position, song_id):
    return {"set_number": set_number, "position": position, "song_id": song_id}


ACTUAL = [_row("1", p, sid) for p, sid in enumerate([10, 20, 30, 40], 1)]


def _atts(calls, bracket=(), early=frozenset(), bustouts=frozenset()):
    foresight, _ = score_foresight(list(bracket), ACTUAL)
    live = score_live(ACTUAL, calls)
    atts = apply_combo(ACTUAL, resolve_claims(foresight, live, ACTUAL), calls)
    return apply_badges(
        atts, early_called_indices=early, bustout_song_ids=bustouts
    )


# --- Task 1.6: flags ----------------------------------------------------------


def test_called_early_badge_no_points():
    atts = _atts({}, early={2})
    assert atts[2]["called_early"] is True
    assert atts[2]["final"] == 0
    assert atts[1]["called_early"] is False


def test_bustout_flag_only_from_explicit_input():
    atts = _atts({}, bustouts={30})
    assert atts[2]["bustout"] is True
    assert atts[2]["missed"] is False  # celebrated, not shamed
    # Song 40: nobody claimed it and it is NOT a bustout -> a plain miss.
    assert atts[3]["bustout"] is False
    assert atts[3]["missed"] is True


def test_claimed_song_is_not_missed():
    atts = _atts({1: 20})
    assert atts[1]["missed"] is False and atts[1]["bustout"] is False


# --- Task 1.7: totals ---------------------------------------------------------


def test_totals_split_by_ledger():
    # Foresight: song 20 exact at ("1",2) -> banks 80 AND advances the streak
    # (correct call). Live: songs 30, 40 called at streak 2 and 3 -> 45 + 60.
    atts = _atts({1: 20, 2: 30, 3: 40}, bracket=[_row("1", 2, 20)])
    totals = summarize(atts)
    assert totals["foresight_total"] == 80
    assert totals["live_total"] == 45 + 60
    assert totals["combined"] == 80 + 45 + 60


def test_ppps_excludes_only_bustouts():
    # 4 songs, one bustout -> denominator 3. Misses stay in the denominator.
    atts = _atts({1: 20}, bustouts={40})
    totals = summarize(atts)
    assert totals["ppps"] == 30 / 3


def test_ppps_denominator_never_zero():
    atts = apply_badges(
        apply_combo([], resolve_claims({}, {}, []), {}),
        early_called_indices=frozenset(),
        bustout_song_ids=frozenset(),
    )
    assert summarize(atts)["ppps"] == 0


def test_hit_counts():
    atts = _atts({2: 30}, bracket=[_row("1", 2, 20)])
    totals = summarize(atts)
    assert totals["hit_counts"] == {"exact": 1, "next_song": 1}
