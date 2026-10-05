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
    assert metrics["ship_gate"]["basis"] == "no_baseline"  # nothing in prod yet
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


TRAIN_RUN = ["train", "run", "--holdout", "2", "--negatives", "3", "--iterations", "10"]


def _cli(monkeypatch, *argv):
    import phishpicker.cli as cli

    monkeypatch.setattr("sys.argv", ["phishpicker", *argv])
    return cli.main()


def _add_shows(data_dir, dates):
    """Shows played after the last training run, with the fixture's setlist."""
    import sqlite3

    conn = sqlite3.connect(data_dir / "phishpicker.db")
    for i, show_date in enumerate(dates):
        show_id = 900 + i
        conn.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at) VALUES (?, ?, ?)",
            (show_id, show_date, show_date),
        )
        conn.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
            [(show_id, "1", pos, song) for pos, song in enumerate((1, 3, 4, 2), start=1)],
        )
    conn.commit()
    conn.close()


def _gate_record(data_dir, exit_code):
    name = "metrics.json" if exit_code == 0 else "metrics.blocked.json"
    return json.loads((data_dir / name).read_text())["ship_gate"]


def test_train_run_grades_the_shipped_model_on_the_new_holdout(env_with_db, monkeypatch, capsys):
    assert _cli(monkeypatch, *TRAIN_RUN) == 0
    _add_shows(env_with_db, ["2025-02-01", "2025-02-08"])
    capsys.readouterr()

    code = _cli(monkeypatch, *TRAIN_RUN)

    assert code in (0, 2)
    gate = _gate_record(env_with_db, code)
    assert gate["basis"] == "same_holdout"
    assert gate["current_model_path"] == str(env_with_db / "model.lgb")
    assert (gate["holdout_first_date"], gate["holdout_last_date"]) == ("2025-02-01", "2025-02-08")
    assert gate["current_mrr"] is not None
    assert gate["summary"] in capsys.readouterr().out


def test_train_run_blocked_by_a_better_current_model_prints_both(env_with_db, monkeypatch, capsys):
    from phishpicker.train import ship_gate
    from phishpicker.train.eval import WalkForwardResult

    assert _cli(monkeypatch, *TRAIN_RUN) == 0
    _add_shows(env_with_db, ["2025-02-01", "2025-02-08"])

    def perfect(conn, booster, n_holdout_shows=20, show_ids=None):
        return WalkForwardResult(fold_results=[], top1=1.0, top5=1.0, top20=1.0, mrr=1.0, n_slots=8)

    monkeypatch.setattr(ship_gate, "evaluate_booster", perfect)
    capsys.readouterr()

    assert _cli(monkeypatch, *TRAIN_RUN) == 2

    out = capsys.readouterr().out
    gate = _gate_record(env_with_db, 2)
    assert gate["passed"] is False
    assert gate["current_mrr"] == 1.0
    assert gate["summary"] in out
    assert "Ship gate blocked" in out
    assert (env_with_db / "model.blocked.lgb").exists()


def test_train_run_current_model_flag_points_the_gate_elsewhere(env_with_db, monkeypatch):
    """Training into a scratch data dir: grade the model that is in prod."""
    assert _cli(monkeypatch, *TRAIN_RUN) == 0
    prod = env_with_db / "prod"
    prod.mkdir()
    for name in ("model.lgb", "model.meta.json", "metrics.json"):
        (env_with_db / name).rename(prod / name)
    _add_shows(env_with_db, ["2025-02-01", "2025-02-08"])

    code = _cli(monkeypatch, *TRAIN_RUN, "--current-model", str(prod / "model.lgb"))

    gate = _gate_record(env_with_db, code)
    assert gate["basis"] == "same_holdout"
    assert gate["current_model_path"] == str(prod / "model.lgb")
