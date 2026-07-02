"""Rank-1 ties must resolve deterministically (score desc, song_id asc) —
otherwise the live next-song call can flip between identical recomputes."""

from phishpicker.predict import predict_next_stateless


class TieScorer:
    """Stub scorer: every candidate gets the same score, returned high-id-first
    (a scorer's output order carries no contract — the final sort must not
    depend on it)."""

    name = "stub"

    def score_candidates(self, *, candidate_song_ids, **kwargs):
        return [(sid, 1.0) for sid in sorted(candidate_song_ids, reverse=True)]


def _tie_db(tmp_path):
    from phishpicker.db.connection import open_db

    conn = open_db(tmp_path / "read.db")
    conn.executescript(
        """
        CREATE TABLE songs (song_id INTEGER PRIMARY KEY, name TEXT);
        -- Inserted high-id-first so raw row order disagrees with song_id order.
        INSERT INTO songs (song_id, name) VALUES (7, 'G'), (3, 'C'), (5, 'E');
        """
    )
    conn.commit()
    return conn


def test_tied_scores_rank_lower_song_id_first(tmp_path):
    conn = _tie_db(tmp_path)
    out = predict_next_stateless(
        read_conn=conn,
        played_songs=[],
        current_set="1",
        show_date="2026-07-07",
        venue_id=None,
        scorer=TieScorer(),
    )
    assert [c["song_id"] for c in out] == [3, 5, 7]


def test_repeat_calls_identical(tmp_path):
    conn = _tie_db(tmp_path)
    kwargs = {
        "read_conn": conn,
        "played_songs": [],
        "current_set": "1",
        "show_date": "2026-07-07",
        "venue_id": None,
        "scorer": TieScorer(),
    }
    first = [c["song_id"] for c in predict_next_stateless(**kwargs)]
    second = [c["song_id"] for c in predict_next_stateless(**kwargs)]
    assert first == second == sorted(first)
