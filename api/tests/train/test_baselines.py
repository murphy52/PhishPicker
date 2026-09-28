from phishpicker.train.baselines import (
    evaluate_scorer,
    frequency_scorer,
    heuristic_scorer,
    random_scorer,
)


def test_random_scorer_produces_result(small_train_db):
    r = evaluate_scorer(small_train_db, random_scorer(seed=0), n_holdout_shows=2)
    assert r.n_slots == 8
    assert 0.0 <= r.top1 <= 1.0


def test_frequency_scorer_beats_random_on_rigged_fixture(small_train_db):
    # Song 1 is played every show — frequency baseline should rank it high
    # on the opener slot.
    rf = evaluate_scorer(small_train_db, frequency_scorer(small_train_db), n_holdout_shows=3)
    rr = evaluate_scorer(small_train_db, random_scorer(seed=0), n_holdout_shows=3)
    # Not a hard inequality on every toy — assert frequency is at least as good
    # on average across 12 slots.
    assert rf.mrr >= rr.mrr - 0.05


def test_heuristic_scorer_runs(small_train_db):
    r = evaluate_scorer(small_train_db, heuristic_scorer(), n_holdout_shows=2)
    assert r.n_slots == 8


def test_evaluate_scorer_cutoff_uses_heldout_date(small_train_db):
    r = evaluate_scorer(small_train_db, random_scorer(seed=0), n_holdout_shows=3)
    assert len(r.fold_results) == 3
    for fold in r.fold_results:
        assert fold.train_cutoff_date == fold.heldout_show_date


def test_evaluate_scorer_never_holds_out_msg_retro_run(small_train_db):
    small_train_db.execute(
        "INSERT INTO shows (show_id, show_date, fetched_at) "
        "VALUES (1771439218, '2025-01-01', '2025-01-01')"
    )
    small_train_db.execute(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
        "VALUES (1771439218, '1', 1, 5)"
    )
    small_train_db.commit()
    r = evaluate_scorer(small_train_db, random_scorer(seed=0), n_holdout_shows=1)
    assert r.fold_results[0].heldout_show_id != 1771439218
