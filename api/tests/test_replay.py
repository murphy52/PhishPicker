"""Tests for the `replay` analysis tool.

Replay compares two LightGBM model artifacts side-by-side on a historical show,
slot by slot. Uses the `small_train_db` fixture for a fast end-to-end path
through the full feature-building + scoring pipeline.
"""

import pytest

from phishpicker.model.lightgbm_scorer import save_model_artifact
from phishpicker.replay import ReplayError, replay_show
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.trainer import train_ranker


@pytest.fixture
def two_trained_models(tmp_path, small_train_db):
    """Train two tiny LightGBM models on the small_train_db fixture and persist
    each as a separate artifact. Returns (path_a, path_b, booster_a, booster_b)."""
    booster_a, cols_a, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=20,
    )
    booster_b, cols_b, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=7,  # different seed → different model
        num_iterations=20,
    )
    path_a = tmp_path / "model_a.lgb"
    path_b = tmp_path / "model_b.lgb"
    save_model_artifact(path_a, booster_a, cols_a)
    save_model_artifact(path_b, booster_b, cols_b)
    return path_a, path_b


@pytest.fixture
def one_trained_model(tmp_path, small_train_db):
    booster, cols, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=20,
    )
    path = tmp_path / "model_only.lgb"
    save_model_artifact(path, booster, cols)
    return path


@pytest.fixture
def known_show_id(small_train_db):
    """The small_train_db fixture seeds show_ids 100..129, each with 4 setlist
    rows. Return one of them for replay tests."""
    row = small_train_db.execute("SELECT show_id FROM shows ORDER BY show_date LIMIT 1").fetchone()
    return int(row["show_id"])


def test_replay_returns_one_result_per_slot(small_train_db, two_trained_models, known_show_id):
    path_a, path_b = two_trained_models
    result = replay_show(
        small_train_db,
        model_a_path=path_a,
        model_b_path=path_b,
        show_id=known_show_id,
    )
    # small_train_db seeds each show with exactly 4 setlist rows.
    assert len(result["slots"]) == 4


def test_replay_result_contains_both_model_ranks(small_train_db, two_trained_models, known_show_id):
    path_a, path_b = two_trained_models
    result = replay_show(
        small_train_db,
        model_a_path=path_a,
        model_b_path=path_b,
        show_id=known_show_id,
    )
    for slot in result["slots"]:
        assert "rank_a" in slot
        assert "rank_b" in slot
        assert isinstance(slot["rank_a"], int)
        assert isinstance(slot["rank_b"], int)
        assert slot["rank_a"] >= 1
        assert slot["rank_b"] >= 1
        assert "delta" in slot
        assert slot["delta"] == slot["rank_b"] - slot["rank_a"]


def test_replay_identical_models_have_zero_delta(small_train_db, one_trained_model, known_show_id):
    """Loading the same model under both paths must yield identical ranks."""
    result = replay_show(
        small_train_db,
        model_a_path=one_trained_model,
        model_b_path=one_trained_model,
        show_id=known_show_id,
    )
    for slot in result["slots"]:
        assert slot["rank_a"] == slot["rank_b"]
        assert slot["delta"] == 0
    assert result["summary"]["b_beats_a_count"] == 0
    assert result["summary"]["a_beats_b_count"] == 0
    assert result["summary"]["mean_rank_a"] == result["summary"]["mean_rank_b"]
    assert result["summary"]["mrr_a"] == pytest.approx(result["summary"]["mrr_b"])


def test_replay_mean_rank_is_in_range(small_train_db, two_trained_models, known_show_id):
    """Sanity: mean ranks must be between 1 and the total number of songs."""
    path_a, path_b = two_trained_models
    n_songs = small_train_db.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    result = replay_show(
        small_train_db,
        model_a_path=path_a,
        model_b_path=path_b,
        show_id=known_show_id,
    )
    for key in ("mean_rank_a", "mean_rank_b"):
        assert 1.0 <= result["summary"][key] <= float(n_songs), f"{key}={result['summary'][key]}"
    for key in ("mrr_a", "mrr_b"):
        assert 0.0 < result["summary"][key] <= 1.0


def test_replay_rejects_schema_mismatch(tmp_path, small_train_db, one_trained_model, known_show_id):
    """If the persisted model's feature_columns don't match FEATURE_COLUMNS,
    replay_show must raise a ReplayError (ValueError subclass)."""
    import json

    # Corrupt model_a's meta.json so its feature_columns list is wrong.
    bad_path = tmp_path / "bad_model.lgb"
    # Copy the good .lgb content, but write a trimmed schema alongside.
    bad_path.write_bytes(one_trained_model.read_bytes())
    bad_path.with_suffix(".meta.json").write_text(
        json.dumps({"feature_columns": list(FEATURE_COLUMNS[:-1])})
    )
    with pytest.raises(ReplayError, match="schema"):
        replay_show(
            small_train_db,
            model_a_path=bad_path,
            model_b_path=one_trained_model,
            show_id=known_show_id,
        )
