from phishpicker.train.eval import walk_forward_eval


def test_walk_forward_runs_one_fold_per_heldout_show(small_train_db):
    result = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert len(result.fold_results) == 3


def test_walk_forward_cutoff_equals_heldout_show_date(small_train_db):
    """Training for fold k uses strictly earlier shows — cutoff == heldout date."""
    result = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    for fold in result.fold_results:
        assert fold.train_cutoff_date == fold.heldout_show_date


def test_walk_forward_reports_topk_and_mrr_in_range(small_train_db):
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert 0.0 <= r.top1 <= 1.0
    assert 0.0 <= r.top5 <= 1.0
    assert 0.0 <= r.top20 <= 1.0
    assert 0.0 <= r.mrr <= 1.0


def test_walk_forward_n_slots_matches_setlist_sum(small_train_db):
    # Fixture: 30 shows × 4 slots = 120 total; last 3 held out = 12 slots.
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert r.n_slots == 12


def test_walk_forward_each_fold_has_rank_per_slot(small_train_db):
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=2,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    for fold in r.fold_results:
        assert len(fold.ranks) == 4  # 4 songs per show in the fixture
        assert all(rk >= 1 for rk in fold.ranks)
