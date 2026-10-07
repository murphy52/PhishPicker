"""full_list mode (the phishvs bundle): top_n candidates by raw score whatever
their sign, excluded songs removed rather than zeroed, softmax probabilities.
The default mode (live next-song call, pushes, web previews) must not move."""

import math

from phishpicker.predict import FULL_LIST_SOFTMAX_T, predict_next_stateless

# Mostly negative raw scores, as LightGBM's often are. Song 4 is played
# tonight and song 6 earlier in the run; both outscore every eligible song
# but one, so zeroing them (the default path) would rank them above the
# negatives.
SCORES = {1: 3.0, 2: 1.0, 3: -0.5, 4: 2.5, 5: -2.0, 6: 0.5, 7: -1.0, 8: -3.0}
PLAYED_TONIGHT = [4]
PLAYED_IN_RUN = {6}


class FixedScorer:
    name = "stub"

    def __init__(self, scores):
        self.scores = scores

    def score_candidates(self, *, candidate_song_ids, **kwargs):
        return [(sid, self.scores[sid]) for sid in candidate_song_ids]


def _db(tmp_path, ids):
    from phishpicker.db.connection import open_db

    conn = open_db(tmp_path / "read.db")
    conn.execute("CREATE TABLE songs (song_id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO songs VALUES (?, ?)", [(i, f"Song {i}") for i in ids])
    conn.commit()
    return conn


def _predict(conn, scores, **kwargs):
    return predict_next_stateless(
        read_conn=conn,
        played_songs=PLAYED_TONIGHT,
        current_set="1",
        show_date="2026-07-07",
        venue_id=None,
        scorer=FixedScorer(scores),
        played_in_run=PLAYED_IN_RUN,
        **kwargs,
    )


def test_default_mode_is_unchanged(tmp_path):
    # Positive scores only, share of their sum — exactly the pre-full_list output.
    out = _predict(_db(tmp_path, SCORES), SCORES)
    assert out == [
        {"song_id": 1, "name": "Song 1", "score": 3.0, "probability": 0.75},
        {"song_id": 2, "name": "Song 2", "score": 1.0, "probability": 0.25},
    ]
    assert out == _predict(_db(tmp_path / "b", SCORES), SCORES, full_list=False)


def test_full_list_returns_top_n_including_negative_scores(tmp_path):
    out = _predict(_db(tmp_path, SCORES), SCORES, top_n=4, full_list=True)
    assert [c["song_id"] for c in out] == [1, 2, 3, 7]
    assert [c["score"] for c in out] == [3.0, 1.0, -0.5, -1.0]


def test_full_list_returns_every_eligible_song_when_fewer_than_top_n(tmp_path):
    out = _predict(_db(tmp_path, SCORES), SCORES, full_list=True)
    assert [c["song_id"] for c in out] == [1, 2, 3, 7, 5, 8]


def test_full_list_drops_excluded_songs_even_when_all_else_is_negative(tmp_path):
    scores = {sid: -abs(s) - 1.0 for sid, s in SCORES.items()}
    scores[4] = scores[6] = -100.0  # excluded songs, below every eligible one
    out = _predict(_db(tmp_path, scores), scores, full_list=True)
    ids = [c["song_id"] for c in out]
    assert len(ids) == 6 and not {4, 6} & set(ids)
    # The default path ships nothing here: no positive scores.
    assert _predict(_db(tmp_path / "b", scores), scores) == []


def test_full_list_ties_break_by_song_id(tmp_path):
    scores = dict.fromkeys(SCORES, -1.0)
    out = _predict(_db(tmp_path, scores), scores, top_n=3, full_list=True)
    assert [c["song_id"] for c in out] == [1, 2, 3]


def test_full_list_probabilities_are_softmax_of_scores(tmp_path):
    out = _predict(_db(tmp_path, SCORES), SCORES, top_n=4, full_list=True)
    probs = [c["probability"] for c in out]
    weights = [math.exp(c["score"] / FULL_LIST_SOFTMAX_T) for c in out]
    expected = [w / sum(weights) for w in weights]
    assert all(math.isclose(p, e, rel_tol=1e-12) for p, e in zip(probs, expected, strict=True))
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-12)
    assert all(p > 0 for p in probs)
    assert probs == sorted(probs, reverse=True)


def test_full_list_softmax_is_stable_for_large_scores(tmp_path):
    scores = {1: 2000.0, 2: 1999.0, 3: -2000.0}
    out = predict_next_stateless(
        read_conn=_db(tmp_path, scores),
        played_songs=[],
        current_set="1",
        show_date="2026-07-07",
        venue_id=None,
        scorer=FixedScorer(scores),
        full_list=True,
    )
    probs = [c["probability"] for c in out]
    assert all(math.isfinite(p) for p in probs)
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-12)
