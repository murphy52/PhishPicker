from phishpicker.train.experiments import era_ab_experiment


def test_era_ab_experiment_runs_both_arms(small_train_db):
    result = era_ab_experiment(
        small_train_db,
        n_holdout_shows=2,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert "era_only" in result
    assert "era_plus_recency" in result
    # Each arm gets an MRR point estimate.
    assert 0.0 <= result["era_only"]["mrr"] <= 1.0
    assert 0.0 <= result["era_plus_recency"]["mrr"] <= 1.0


def test_era_ab_produces_verdict(small_train_db):
    result = era_ab_experiment(
        small_train_db,
        n_holdout_shows=2,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    # Verdict is one of a small enum.
    assert result["verdict"] in {"ship_era_only", "ship_era_plus_recency"}
