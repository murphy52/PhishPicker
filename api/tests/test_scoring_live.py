"""Live next-song base scoring (Task 1.3) and best-claim-wins resolution
(Task 1.4)."""

from phishpicker.scoring import (
    PTS_EXACT,
    PTS_NEXT_SONG,
    PTS_SOMEWHERE,
    resolve_claims,
    score_foresight,
    score_live,
)


def _row(set_number, position, song_id):
    return {"set_number": set_number, "position": position, "song_id": song_id}


ACTUAL = [_row("1", 1, 10), _row("1", 2, 20), _row("2", 1, 30)]


# --- Task 1.3: live base ------------------------------------------------------


def test_correct_call_scores_base():
    live = score_live(ACTUAL, {1: 20})
    assert live[1]["base"] == PTS_NEXT_SONG


def test_wrong_call_scores_nothing():
    live = score_live(ACTUAL, {1: 999})
    assert 1 not in live


def test_index_zero_never_a_live_event():
    # Even a (nonsensical) captured call for the opener is ignored.
    live = score_live(ACTUAL, {0: 10})
    assert live == {}


def test_no_call_no_claim():
    assert score_live(ACTUAL, {}) == {}


# --- Task 1.4: best-claim-wins ------------------------------------------------


def test_foresight_exact_beats_live():
    foresight, _ = score_foresight([_row("1", 2, 20)], ACTUAL)  # exact 40
    live = score_live(ACTUAL, {1: 20})  # 30
    atts = resolve_claims(foresight, live, ACTUAL)
    assert atts[1]["ledger"] == "foresight"
    assert atts[1]["base"] == PTS_EXACT
    assert atts[1]["beaten_claim"] == {
        "ledger": "live",
        "reason": "next_song",
        "base": PTS_NEXT_SONG,
    }


def test_live_beats_foresight_somewhere():
    foresight, _ = score_foresight([_row("2", 4, 20)], ACTUAL)  # somewhere 5
    live = score_live(ACTUAL, {1: 20})  # 30
    atts = resolve_claims(foresight, live, ACTUAL)
    assert atts[1]["ledger"] == "live"
    assert atts[1]["base"] == PTS_NEXT_SONG
    assert atts[1]["beaten_claim"] == {
        "ledger": "foresight",
        "reason": "somewhere",
        "base": PTS_SOMEWHERE,
    }


def test_one_attribution_per_actual_song():
    foresight, _ = score_foresight([_row("1", 2, 20)], ACTUAL)
    live = score_live(ACTUAL, {1: 20, 2: 30})
    atts = resolve_claims(foresight, live, ACTUAL)
    assert len(atts) == len(ACTUAL)
    assert [a["index"] for a in atts] == [0, 1, 2]
    assert atts[0]["ledger"] is None  # opener: no claim from either ledger
    assert atts[0]["base"] == 0


def test_tie_goes_to_foresight():
    # Contrived: equal bases must bank Foresight (premium tier).
    foresight = {1: {"base": PTS_NEXT_SONG, "reason": "contrived", "pick": None}}
    live = score_live(ACTUAL, {1: 20})
    atts = resolve_claims(foresight, live, ACTUAL)
    assert atts[1]["ledger"] == "foresight"
