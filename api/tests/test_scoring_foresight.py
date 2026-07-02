"""Foresight ledger: classification of a single bracket pick (Task 1.1) and
the whole-bracket pass with opener bonus + consume-once (Task 1.2)."""

from phishpicker.scoring import (
    PTS_EXACT,
    PTS_OPENER,
    PTS_RIGHT_SET,
    PTS_SOMEWHERE,
    classify_foresight,
    score_foresight,
)


def _row(set_number, position, song_id):
    return {"set_number": set_number, "position": position, "song_id": song_id}


ACTUAL = [_row("1", 1, 10), _row("1", 2, 20), _row("2", 1, 30)]


# --- Task 1.1: classification -------------------------------------------------


def test_exact():
    assert classify_foresight(_row("1", 1, 10), ACTUAL) == ("exact", PTS_EXACT)


def test_right_set():
    assert classify_foresight(_row("1", 5, 20), ACTUAL) == ("right_set", PTS_RIGHT_SET)


def test_somewhere():
    # song 20 played in set 1, pick says set 2
    assert classify_foresight(_row("2", 3, 20), ACTUAL) == ("somewhere", PTS_SOMEWHERE)


def test_absent():
    assert classify_foresight(_row("1", 1, 999), ACTUAL) == ("absent", 0)


def test_best_occurrence_wins():
    # song 40 plays twice: set 1 pos 3 (right set for the pick) and set 2
    # pos 2 (exact for the pick) — exact must win.
    actual = [_row("1", 3, 40), _row("2", 2, 40)]
    assert classify_foresight(_row("2", 2, 40), actual) == ("exact", PTS_EXACT)


# --- Task 1.2: whole-bracket ledger -------------------------------------------


def test_opener_exact_gets_bonus():
    claims, _ = score_foresight([_row("1", 1, 10)], ACTUAL)
    assert claims[0]["base"] == PTS_OPENER
    assert claims[0]["reason"] == "opener"


def test_e2_opener_is_plain_exact():
    actual = [_row("E2", 1, 50)]
    claims, _ = score_foresight([_row("E2", 1, 50)], actual)
    assert claims[0]["base"] == PTS_EXACT
    assert claims[0]["reason"] == "exact"


def test_claims_keyed_by_actual_index():
    claims, _ = score_foresight([_row("1", 5, 20)], ACTUAL)
    assert set(claims.keys()) == {1}  # song 20 is actual[1]
    assert claims[1]["reason"] == "right_set"


def test_consume_once_for_repeated_song():
    # Song 40 plays twice; the single bracket pick claims its best occurrence
    # only — the other occurrence gets no Foresight claim.
    actual = [_row("1", 3, 40), _row("2", 2, 40)]
    claims, _ = score_foresight([_row("2", 2, 40)], actual)
    assert set(claims.keys()) == {1}


def test_pick_outcomes_include_absent_picks():
    picks = [_row("1", 1, 10), _row("2", 5, 999)]
    _, outcomes = score_foresight(picks, ACTUAL)
    assert len(outcomes) == 2
    by_song = {o["pick"]["song_id"]: o for o in outcomes}
    assert by_song[10]["reason"] == "opener"
    assert by_song[10]["actual_index"] == 0
    assert by_song[999]["reason"] == "absent"
    assert by_song[999]["actual_index"] is None
    assert by_song[999]["base"] == 0
