"""End-to-end training runner.

`run_training` wires together: train production model → walk-forward eval →
baselines → ship-gate check → atomic write of (model.lgb, metrics.json).

The atomic write uses a `.tmp` sidecar + rename so a concurrent API reload
never sees a partial artifact. The API's /internal/reload endpoint is what
tells the running service to re-open the new model.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from phishpicker.model.lightgbm_scorer import save_model_artifact
from phishpicker.train.baselines import (
    evaluate_scorer,
    frequency_scorer,
    heuristic_scorer,
    random_scorer,
)
from phishpicker.train.eval import WalkForwardResult, walk_forward_eval
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.ship_gate import ship_gate_check
from phishpicker.train.trainer import train_ranker

MODEL_VERSION = "0.2.0-lightgbm"


def _result_summary(r: WalkForwardResult) -> dict:
    return {
        "top1": r.top1,
        "top5": r.top5,
        "top20": r.top20,
        "mrr": r.mrr,
    }


def run_training(
    conn,
    data_dir: Path,
    cutoff_date: str | None = None,
    n_holdout_shows: int = 20,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    num_iterations: int = 300,
    half_life_years: float | None = 7.0,
    seed: int = 0,
    override_ship_gate: bool = False,
    n_resamples: int = 1000,
) -> dict:
    """Train, evaluate, and (if gate passes) write artifacts. Returns the
    metrics dict that was persisted."""
    if cutoff_date is None:
        # Use the latest show *with a setlist*, not just the latest show — phish.net
        # lists future-dated placeholders with no setlist rows yet.
        row = conn.execute(
            "SELECT MAX(s.show_date) FROM shows s "
            "WHERE EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)"
        ).fetchone()
        latest = row[0] if row and row[0] else None
        cutoff_date = _plus_one_day(latest) if latest else datetime.now(UTC).date().isoformat()

    # 1. Production model: trained on ALL data (cutoff = day after latest show).
    booster, cols, n_groups_prod = train_ranker(
        conn,
        cutoff_date=cutoff_date,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        num_iterations=num_iterations,
        half_life_years=half_life_years,
        seed=seed,
    )

    # 2. Walk-forward evaluation (reports holdout metrics).
    wf = walk_forward_eval(
        conn,
        n_holdout_shows=n_holdout_shows,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        num_iterations=num_iterations,
        half_life_years=half_life_years,
        seed=seed,
    )

    # 3. Baselines on same holdout.
    baselines = {
        "random": _result_summary(
            evaluate_scorer(conn, random_scorer(seed=seed), n_holdout_shows=n_holdout_shows)
        ),
        "frequency": _result_summary(
            evaluate_scorer(conn, frequency_scorer(), n_holdout_shows=n_holdout_shows)
        ),
        "heuristic": _result_summary(
            evaluate_scorer(conn, heuristic_scorer(), n_holdout_shows=n_holdout_shows)
        ),
    }

    # 4. Ship gate.
    metrics_path = Path(data_dir) / "metrics.json"
    gate_passed = ship_gate_check(new_mrr=wf.mrr, previous_metrics_path=metrics_path)
    if not gate_passed and not override_ship_gate:
        return {
            "ship_gate_passed": False,
            "reason": "mrr_regression_exceeds_tolerance",
            "new_mrr": wf.mrr,
            "wrote_artifacts": False,
        }

    # 5. Atomic artifact write.
    n_shows = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
    metrics = {
        "trained_at": datetime.now(UTC).isoformat(),
        "cutoff_date": cutoff_date,
        "n_shows_trained_on": int(n_shows),
        "n_groups_trained_on": int(n_groups_prod),
        "n_slots": int(wf.n_slots),
        "holdout_shows": n_holdout_shows,
        "top1": wf.top1,
        "top5": wf.top5,
        "top20": wf.top20,
        "mrr": wf.mrr,
        "top1_ci": list(wf.top1_ci),
        "top5_ci": list(wf.top5_ci),
        "top20_ci": list(wf.top20_ci),
        "mrr_ci": list(wf.mrr_ci),
        "by_slot": {str(k): v for k, v in wf.by_slot.items()},
        "baselines": baselines,
        "ship_gate_passed": gate_passed,
        "model_version": MODEL_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
    }

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    model_path = data_dir / "model.lgb"
    tmp_model = data_dir / "model.lgb.tmp"
    save_model_artifact(tmp_model, booster, cols)
    # Atomic rename for both the booster text file and its .meta.json sidecar.
    os.replace(tmp_model, model_path)
    os.replace(
        tmp_model.with_suffix(".meta.json"),
        model_path.with_suffix(".meta.json"),
    )

    tmp_metrics = data_dir / "metrics.json.tmp"
    tmp_metrics.write_text(json.dumps(metrics, indent=2))
    os.replace(tmp_metrics, metrics_path)

    return {**metrics, "wrote_artifacts": True}


def _plus_one_day(iso_date: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(iso_date) + timedelta(days=1)).isoformat()
