import json

import pytest


@pytest.fixture
def env_with_db(monkeypatch, tmp_path, small_train_db):
    """Set env so the CLI opens small_train_db's parent dir as PHISHPICKER_DATA_DIR."""
    # small_train_db creates tmp_path / "train.db"; the CLI expects phishpicker.db.
    # Rename to the canonical name so cli picks it up.
    src_path = small_train_db.execute("PRAGMA database_list").fetchone()[2]
    small_train_db.close()
    from pathlib import Path

    src = Path(src_path)
    dst = src.parent / "phishpicker.db"
    src.rename(dst)
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(src.parent))
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    return src.parent


def test_train_run_writes_model_and_metrics(env_with_db):
    # Drive the CLI by importing main() directly to share the monkeypatched env.
    # argparse reads sys.argv; patch it.
    import sys as _sys

    import phishpicker.cli as cli

    _sys.argv = [
        "phishpicker",
        "train",
        "run",
        "--holdout",
        "2",
        "--negatives",
        "3",
        "--iterations",
        "10",
    ]
    result = cli.main()
    assert result == 0
    assert (env_with_db / "model.lgb").exists()
    assert (env_with_db / "model.meta.json").exists()
    assert (env_with_db / "metrics.json").exists()
    metrics = json.loads((env_with_db / "metrics.json").read_text())
    assert metrics["ship_gate_passed"] is True
    assert metrics["n_slots"] > 0
    assert "baselines" in metrics
    assert "by_slot" in metrics
    assert len(metrics["feature_columns"]) >= 25


def test_train_eval_model_grades_an_artifact_on_the_holdout(env_with_db, capsys):
    import sys as _sys

    import phishpicker.cli as cli

    _sys.argv = [
        "phishpicker",
        "train",
        "run",
        "--holdout",
        "2",
        "--negatives",
        "3",
        "--iterations",
        "10",
    ]
    assert cli.main() == 0
    capsys.readouterr()

    _sys.argv = [
        "phishpicker",
        "train",
        "eval-model",
        str(env_with_db / "model.lgb"),
        "--holdout",
        "2",
    ]
    assert cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    trained = json.loads((env_with_db / "metrics.json").read_text())
    assert out["n_slots"] == trained["n_slots"]
    assert len(out["shows"]) == 2
    assert {"top1", "top5", "top20", "mrr", "mrr_ci"} <= out.keys()
