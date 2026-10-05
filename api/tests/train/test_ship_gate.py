import json
from dataclasses import replace

import lightgbm as lgb
import numpy as np
import pytest

from phishpicker.model.lightgbm_scorer import LightGBMScorer, save_model_artifact
from phishpicker.train import ship_gate
from phishpicker.train.eval import (
    FoldResult,
    WalkForwardResult,
    evaluate_booster,
    select_holdout_shows,
)
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.ship_gate import check_against_current_model, ship_gate_check
from phishpicker.train.trainer import train_ranker


def test_first_ship_always_passes(tmp_path):
    metrics_path = tmp_path / "metrics.json"
    assert ship_gate_check(new_mrr=0.10, previous_metrics_path=metrics_path) is True


def test_ship_passes_when_new_is_better(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.15}))
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p) is True


def test_ship_passes_when_regression_within_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # 0.005 drop, tolerance 0.02 → OK.
    assert ship_gate_check(new_mrr=0.195, previous_metrics_path=p) is True


def test_ship_fails_when_regression_exceeds_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # 0.03 drop > 0.02 tolerance → block.
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p) is False


def test_custom_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # With tolerance 0.05 a 0.03 drop is OK.
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p, max_drop=0.05) is True


# --- check_against_current_model: grade the current model on the same shows ---

HOLDOUT = 3
# small_train_db's last three shows are 2024-11-23, 2024-12-12 and 2024-12-24.
BEFORE_HOLDOUT = "2024-06-01"


def _folds(conn, ranks=(1, 2, 3, 4)):
    return [
        FoldResult(
            heldout_show_id=int(sh["show_id"]),
            heldout_show_date=sh["show_date"],
            train_cutoff_date=sh["show_date"],
            ranks=list(ranks),
        )
        for sh in select_holdout_shows(conn, HOLDOUT)
    ]


def _result(mrr, folds):
    return WalkForwardResult(
        fold_results=folds,
        top1=0.0,
        top5=0.0,
        top20=0.0,
        mrr=mrr,
        n_slots=sum(len(f.ranks) for f in folds),
    )


def _write_metrics(path, **fields):
    path.write_text(json.dumps(fields))
    return path


@pytest.fixture
def current_model(small_train_db, tmp_path):
    """A real (tiny) model artifact standing in for the one in prod."""
    booster, cols, _ = train_ranker(
        small_train_db,
        cutoff_date="2099-01-01",
        negatives_per_positive=3,
        num_iterations=10,
        seed=0,
    )
    path = tmp_path / "prod" / "model.lgb"
    save_model_artifact(path, booster, cols)
    return path


@pytest.fixture
def grade_current_as(monkeypatch):
    """Stand in for evaluate_booster: the current model scores `mrr` on
    whatever shows it is asked about. Returns the list of calls."""
    calls = []

    def install(mrr):
        def fake(conn, booster, n_holdout_shows=20, show_ids=None):
            calls.append({"n_holdout_shows": n_holdout_shows, "show_ids": set(show_ids)})
            return _result(mrr, [f for f in _folds(conn) if f.heldout_show_id in show_ids])

        monkeypatch.setattr(ship_gate, "evaluate_booster", fake)
        return calls

    return install


def test_v12_case_worse_than_current_on_same_holdout_is_blocked(
    small_train_db, current_model, grade_current_as
):
    """2026-09-28: on the same 20 shows v12 scored MRR 0.152 and v11 0.159. The
    old gate passed v12 because it compared against v11's own metrics.json
    (0.143), which was graded in April on different shows."""
    stale = _write_metrics(
        current_model.parent / "metrics.json", mrr=0.143, cutoff_date=BEFORE_HOLDOUT
    )
    assert ship_gate_check(new_mrr=0.152, previous_metrics_path=stale) is True  # the bug

    calls = grade_current_as(0.159)
    folds = _folds(small_train_db)
    gate = check_against_current_model(
        small_train_db,
        _result(0.152, folds),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )

    assert gate.passed is False
    assert gate.basis == "same_holdout"
    assert gate.candidate_mrr == pytest.approx(0.152)
    assert gate.current_mrr == pytest.approx(0.159)
    assert calls == [{"n_holdout_shows": HOLDOUT, "show_ids": {f.heldout_show_id for f in folds}}]
    assert gate.holdout_first_date == "2024-11-23"
    assert gate.holdout_last_date == "2024-12-24"
    assert gate.holdout_n_shows == 3
    for text in ("0.152", "0.159", "2024-11-23", "2024-12-24", "BLOCK"):
        assert text in gate.summary


@pytest.mark.parametrize("candidate_mrr", [0.159, 0.165])
def test_candidate_level_with_or_better_than_current_passes(
    small_train_db, current_model, grade_current_as, candidate_mrr
):
    _write_metrics(current_model.parent / "metrics.json", mrr=0.143, cutoff_date=BEFORE_HOLDOUT)
    grade_current_as(0.159)
    gate = check_against_current_model(
        small_train_db,
        _result(candidate_mrr, _folds(small_train_db)),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert gate.passed is True
    assert gate.basis == "same_holdout"
    assert "PASS" in gate.summary


def test_current_model_is_graded_by_evaluate_booster(small_train_db, current_model, tmp_path):
    """No fakes: the gate's number for the current model is eval-model's."""
    _write_metrics(current_model.parent / "metrics.json", mrr=0.5, cutoff_date=BEFORE_HOLDOUT)
    booster = LightGBMScorer.load(current_model).booster
    expected = evaluate_booster(small_train_db, booster, n_holdout_shows=HOLDOUT)

    gate = check_against_current_model(
        small_train_db,
        replace(expected, mrr=expected.mrr - 0.001),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert gate.basis == "same_holdout"
    assert gate.current_mrr == pytest.approx(expected.mrr)
    assert gate.passed is False


def test_only_shows_the_current_model_never_trained_on_are_compared(
    small_train_db, current_model, grade_current_as
):
    """Graded on shows it trained on, the current model looks better than it
    is. With a cutoff of 2024-12-13 it trained on 2024-11-23 and 2024-12-12,
    so only 2024-12-24 is a fair comparison, for both models."""
    _write_metrics(current_model.parent / "metrics.json", mrr=0.5, cutoff_date="2024-12-13")
    calls = grade_current_as(0.5)
    folds = _folds(small_train_db, ranks=(10, 10, 10, 10))
    latest = folds[-1]
    folds[-1] = replace(latest, ranks=[1, 1, 1, 1])
    candidate = _result(0.4, folds)  # (4 x 1/1 + 8 x 1/10) / 12 over all three shows

    gate = check_against_current_model(
        small_train_db,
        candidate,
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert calls[0]["show_ids"] == {latest.heldout_show_id}
    assert gate.basis == "same_holdout"
    assert gate.candidate_mrr == pytest.approx(1.0)
    assert gate.current_mrr == pytest.approx(0.5)
    assert gate.passed is True
    assert gate.holdout_n_shows == 1
    assert gate.holdout_first_date == gate.holdout_last_date == "2024-12-24"
    assert "2 of 3" in gate.summary


def test_current_model_trained_on_every_holdout_show_falls_back_to_metrics(
    small_train_db, current_model, grade_current_as
):
    _write_metrics(current_model.parent / "metrics.json", mrr=0.20, cutoff_date="2099-01-01")
    calls = grade_current_as(0.5)
    gate = check_against_current_model(
        small_train_db,
        _result(0.17, _folds(small_train_db)),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert calls == []
    assert gate.basis == "previous_metrics"
    assert gate.previous_metrics_mrr == pytest.approx(0.20)
    assert gate.max_drop == pytest.approx(0.02)
    assert gate.passed is False  # 0.03 drop > the old 0.02 tolerance
    assert "trained on all 3" in gate.summary


def test_unknown_training_cutoff_compares_every_show_and_says_so(
    small_train_db, current_model, grade_current_as
):
    calls = grade_current_as(0.159)
    folds = _folds(small_train_db)
    gate = check_against_current_model(
        small_train_db,
        _result(0.165, folds),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert calls[0]["show_ids"] == {f.heldout_show_id for f in folds}
    assert gate.basis == "same_holdout"
    assert gate.passed is True
    assert "cutoff is unknown" in gate.summary


def test_no_current_model_passes_and_says_so(small_train_db, tmp_path):
    gate = check_against_current_model(
        small_train_db,
        _result(0.05, _folds(small_train_db)),
        current_model_path=tmp_path / "model.lgb",
        n_holdout_shows=HOLDOUT,
    )
    assert gate.passed is True
    assert gate.basis == "no_baseline"
    assert gate.current_mrr is None
    assert "no current model" in gate.summary
    assert str(tmp_path / "model.lgb") in gate.summary


def test_missing_current_model_falls_back_to_previous_metrics(small_train_db, tmp_path):
    _write_metrics(tmp_path / "metrics.json", mrr=0.20, cutoff_date=BEFORE_HOLDOUT)
    gate = check_against_current_model(
        small_train_db,
        _result(0.17, _folds(small_train_db)),
        current_model_path=tmp_path / "model.lgb",
        n_holdout_shows=HOLDOUT,
    )
    assert gate.basis == "previous_metrics"
    assert gate.passed is False
    assert "different shows" in gate.summary


def test_incompatible_current_model_falls_back_without_crashing(
    small_train_db, current_model, grade_current_as
):
    """E.g. a 42-feature model against a 44-feature builder."""
    current_model.with_suffix(".meta.json").write_text(
        json.dumps({"feature_columns": list(FEATURE_COLUMNS[:-2])})
    )
    _write_metrics(current_model.parent / "metrics.json", mrr=0.143, cutoff_date=BEFORE_HOLDOUT)
    calls = grade_current_as(0.5)
    gate = check_against_current_model(
        small_train_db,
        _result(0.152, _folds(small_train_db)),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert calls == []
    assert gate.basis == "previous_metrics"
    assert gate.current_mrr is None
    assert gate.previous_metrics_mrr == pytest.approx(0.143)
    assert gate.passed is True  # within the old 0.02 tolerance of a different holdout
    assert f"model has {len(FEATURE_COLUMNS) - 2} columns" in gate.summary


def test_incompatible_current_model_and_no_metrics_passes(small_train_db, current_model):
    current_model.with_suffix(".meta.json").write_text(
        json.dumps({"feature_columns": list(FEATURE_COLUMNS[:-2])})
    )
    gate = check_against_current_model(
        small_train_db,
        _result(0.05, _folds(small_train_db)),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    assert gate.passed is True
    assert gate.basis == "no_baseline"
    assert "can't grade" in gate.summary


def test_unreadable_current_model_falls_back_without_crashing(small_train_db, tmp_path):
    (tmp_path / "model.lgb").write_text("not a model")
    gate = check_against_current_model(
        small_train_db,
        _result(0.05, _folds(small_train_db)),
        current_model_path=tmp_path / "model.lgb",
        n_holdout_shows=HOLDOUT,
    )
    assert gate.passed is True
    assert gate.basis == "no_baseline"
    assert "can't grade" in gate.summary


def test_booster_that_disagrees_with_its_meta_falls_back_without_crashing(small_train_db, tmp_path):
    """The .meta.json says the current feature set, but the booster was fitted
    on 3 features, so scoring it fails. That must not throw away the run."""
    rng = np.random.default_rng(0)
    booster = lgb.train(
        {"objective": "regression", "verbose": -1},
        lgb.Dataset(rng.random((50, 3)), label=rng.random(50)),
        num_boost_round=2,
    )
    save_model_artifact(tmp_path / "model.lgb", booster, list(FEATURE_COLUMNS))
    _write_metrics(tmp_path / "metrics.json", mrr=0.20, cutoff_date=BEFORE_HOLDOUT)

    gate = check_against_current_model(
        small_train_db,
        _result(0.25, _folds(small_train_db)),
        current_model_path=tmp_path / "model.lgb",
        n_holdout_shows=HOLDOUT,
    )
    assert gate.basis == "previous_metrics"
    assert gate.passed is True
    assert "can't grade" in gate.summary


def test_gate_record_is_json_ready(small_train_db, current_model, grade_current_as):
    grade_current_as(0.159)
    gate = check_against_current_model(
        small_train_db,
        _result(0.152, _folds(small_train_db)),
        current_model_path=current_model,
        n_holdout_shows=HOLDOUT,
    )
    record = json.loads(json.dumps(gate.to_dict()))
    assert record["basis"] == "same_holdout"
    assert record["passed"] is False
    assert record["candidate_mrr"] == pytest.approx(0.152)
    assert record["current_mrr"] == pytest.approx(0.159)
    assert record["current_model_path"] == str(current_model)
    assert record["summary"] == gate.summary
