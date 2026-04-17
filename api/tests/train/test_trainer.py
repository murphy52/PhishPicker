import numpy as np

from phishpicker.train.build import build_feature_rows
from phishpicker.train.trainer import train_ranker


def test_train_ranker_returns_booster_and_columns(small_train_db):
    booster, feature_names, n_groups = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=20,
    )
    assert booster is not None
    assert len(feature_names) >= 25
    assert n_groups > 0


def test_trained_ranker_prefers_frequent_opener(small_train_db):
    """Song 1 is always the set-1 opener; song 5 is never played. A trained
    model should rank song 1 > song 5 for the opener slot."""
    booster, _, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=80,
    )
    rows = build_feature_rows(
        small_train_db,
        show_date="2025-02-01",
        venue_id=None,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 5],
    )
    X = np.array([r.to_vector() for r in rows])
    scores = booster.predict(X)
    assert scores[0] > scores[1]


def test_train_ranker_handles_stratified_kwargs(small_train_db):
    booster, _, n_groups = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        freq_negatives=1,
        uniform_negatives=1,
        seed=0,
        num_iterations=10,
    )
    assert booster is not None
    assert n_groups > 0


def test_recency_weight_decays_older_shows(small_train_db):
    """Sanity: half_life_years=None disables weighting (all weights 1.0)."""
    from phishpicker.train.trainer import _recency_weight

    assert _recency_weight("2024-01-01", "2024-12-31", None) == 1.0
    w_recent = _recency_weight("2024-12-01", "2024-12-31", 7.0)
    w_old = _recency_weight("2010-01-01", "2024-12-31", 7.0)
    assert w_old < w_recent
