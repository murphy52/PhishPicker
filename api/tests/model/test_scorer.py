import pytest

from phishpicker.model.scorer import (
    HeuristicScorer,
    LightGBMRuntimeScorer,
    load_runtime_scorer,
)


@pytest.fixture
def trained_model_path(tmp_path, small_train_db):
    from phishpicker.model.lightgbm_scorer import save_model_artifact
    from phishpicker.train.trainer import train_ranker

    booster, cols, _ = train_ranker(
        small_train_db,
        cutoff_date="2025-01-01",
        negatives_per_positive=3,
        seed=0,
        num_iterations=20,
    )
    art = tmp_path / "model.lgb"
    save_model_artifact(art, booster, cols)
    return art


def test_heuristic_scorer_returns_pairs(small_train_db):
    s = HeuristicScorer()
    out = s.score_candidates(
        conn=small_train_db,
        show_date="2025-02-01",
        venue_id=None,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 2, 3],
    )
    assert len(out) == 3
    assert {sid for sid, _ in out} == {1, 2, 3}


def test_lightgbm_runtime_scorer_returns_pairs(small_train_db, trained_model_path):
    from phishpicker.model.lightgbm_scorer import LightGBMScorer

    loaded = LightGBMScorer.load(trained_model_path)
    s = LightGBMRuntimeScorer(scorer=loaded)
    out = s.score_candidates(
        conn=small_train_db,
        show_date="2025-02-01",
        venue_id=None,
        played_songs=[],
        current_set="1",
        candidate_song_ids=[1, 5],
    )
    assert len(out) == 2
    # Trained signal says song 1 > song 5 as opener.
    by_id = dict(out)
    assert by_id[1] > by_id[5]


def test_load_runtime_scorer_falls_back_when_file_missing(tmp_path):
    scorer = load_runtime_scorer(tmp_path / "nonexistent.lgb")
    assert scorer.name == "heuristic"


def test_load_runtime_scorer_loads_lightgbm_when_present(trained_model_path):
    scorer = load_runtime_scorer(trained_model_path)
    assert scorer.name == "lightgbm"


def test_load_runtime_scorer_falls_back_on_schema_mismatch(
    tmp_path, small_train_db, trained_model_path
):
    import json

    # Corrupt the sidecar to simulate a schema mismatch.
    meta = trained_model_path.with_suffix(".meta.json")
    meta.write_text(json.dumps({"feature_columns": ["dropped_column"]}))
    scorer = load_runtime_scorer(trained_model_path)
    assert scorer.name == "heuristic"
