from phishpicker.train.eval import evaluate_booster, select_holdout_shows, walk_forward_eval
from phishpicker.train.trainer import train_ranker

MSG_RETRO_SHOW_ID = 1771439218  # 2026-07-22 MSG, 1992–96 retro sets


def _add_msg_retro_show(conn, show_date):
    conn.execute(
        "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
        (MSG_RETRO_SHOW_ID, show_date, show_date),
    )
    conn.executemany(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
        [(MSG_RETRO_SHOW_ID, "1", i, s) for i, s in enumerate((5, 4, 3, 2), start=1)],
    )
    conn.commit()


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
        assert len(fold.slot_positions) == 4
        assert all(rk >= 1 for rk in fold.ranks)


def test_walk_forward_skips_future_dated_empty_shows(small_train_db):
    """phish.net lists future-dated placeholder shows with no setlist rows.
    Holdout selection must skip those or walk-forward yields n_slots=0."""
    # Insert a future placeholder show with no setlist rows.
    small_train_db.execute(
        "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (9999, '2099-12-31', '2099-12-31')"
    )
    small_train_db.commit()
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=1,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    # The one holdout show should be the latest one with setlist data, NOT 2099.
    assert r.n_slots > 0
    assert r.fold_results[0].heldout_show_id != 9999


def test_walk_forward_reports_ci_and_per_slot(small_train_db):
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert r.top1_ci[0] <= r.top1 <= r.top1_ci[1] + 1e-9
    assert r.mrr_ci[0] <= r.mrr <= r.mrr_ci[1] + 1e-9
    # 4 slots per show in the fixture.
    assert set(r.by_slot.keys()) == {1, 2, 3, 4}
    for slot_metrics in r.by_slot.values():
        assert 0.0 <= slot_metrics["top1"] <= 1.0


def test_holdout_skips_excluded_shows_and_backfills(small_train_db):
    latest = select_holdout_shows(small_train_db, 3, excluded_show_ids=frozenset())
    skipped = latest[-1]["show_id"]
    held = select_holdout_shows(small_train_db, 3, excluded_show_ids={skipped})
    held_ids = [r["show_id"] for r in held]
    assert len(held_ids) == 3
    assert skipped not in held_ids
    # The two survivors are still there; the gap is filled by the next-oldest show.
    assert {r["show_id"] for r in latest[:-1]} <= set(held_ids)


def test_holdout_is_chronological(small_train_db):
    held = select_holdout_shows(small_train_db, 5)
    dates = [r["show_date"] for r in held]
    assert dates == sorted(dates)


def test_walk_forward_never_holds_out_msg_retro_run(small_train_db):
    _add_msg_retro_show(small_train_db, "2025-01-01")  # the latest show in the DB
    r = walk_forward_eval(
        small_train_db,
        n_holdout_shows=1,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    assert r.fold_results[0].heldout_show_id != MSG_RETRO_SHOW_ID


def test_evaluate_booster_scores_the_walk_forward_holdout(small_train_db):
    """A fixed artifact (e.g. the model in prod) is scored on exactly the shows
    and slots walk-forward holds out, so the two are comparable."""
    booster, _, _ = train_ranker(
        small_train_db,
        cutoff_date="2099-01-01",
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    wf = walk_forward_eval(
        small_train_db,
        n_holdout_shows=3,
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    r = evaluate_booster(small_train_db, booster, n_holdout_shows=3)
    assert [f.heldout_show_id for f in r.fold_results] == [
        f.heldout_show_id for f in wf.fold_results
    ]
    assert r.n_slots == wf.n_slots
    assert 0.0 < r.mrr <= 1.0


def test_evaluate_booster_can_narrow_to_given_shows(small_train_db):
    """The ship gate grades the current model on exactly the shows it compares,
    which can be fewer than the full holdout."""
    booster, _, _ = train_ranker(
        small_train_db,
        cutoff_date="2099-01-01",
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    full = evaluate_booster(small_train_db, booster, n_holdout_shows=3)
    kept = full.fold_results[1:]
    r = evaluate_booster(
        small_train_db,
        booster,
        n_holdout_shows=3,
        show_ids={f.heldout_show_id for f in kept},
    )
    assert [f.heldout_show_id for f in r.fold_results] == [f.heldout_show_id for f in kept]
    assert r.n_slots == sum(len(f.ranks) for f in kept)
