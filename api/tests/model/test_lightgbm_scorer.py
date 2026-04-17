import numpy as np
import pytest

from phishpicker.model.lightgbm_scorer import LightGBMScorer, save_model_artifact
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.trainer import train_ranker


@pytest.fixture
def trained_booster(small_train_db):
    booster, cols, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=20,
    )
    return booster, cols


def test_roundtrip_saves_and_loads_booster(tmp_path, trained_booster):
    booster, cols = trained_booster
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    assert scorer.feature_columns == cols


def test_loaded_scorer_produces_same_scores_as_original(tmp_path, trained_booster):
    booster, cols = trained_booster
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    X = np.zeros((3, len(cols)), dtype=np.float32)
    X[:, 0] = [10, 20, 30]  # inject a differing first feature
    assert np.allclose(booster.predict(X), scorer.score(X))


def test_assert_compatible_raises_on_column_mismatch(tmp_path, trained_booster):
    booster, cols = trained_booster
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    scorer.feature_columns = cols[:-1]  # tamper
    with pytest.raises(ValueError, match="schema"):
        scorer.assert_compatible_with(FEATURE_COLUMNS)


def test_assert_compatible_passes_when_columns_match(tmp_path, trained_booster):
    booster, cols = trained_booster
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    scorer = LightGBMScorer.load(art)
    scorer.assert_compatible_with(FEATURE_COLUMNS)
