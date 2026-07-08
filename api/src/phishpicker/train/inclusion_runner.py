"""Train + evaluate + ship the show-level inclusion model.

Produces `inclusion_model.lgb` (+ `.meta.json`) alongside the slot-ranker
`model.lgb`. Evaluation reports Recall@K vs a plays_last_12mo frequency
baseline on a time-based holdout — the spike's headline metric.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np

from phishpicker.model.lightgbm_scorer import save_model_artifact
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    build_training_data,
)

TOPK = 25
DEFAULT_HOLDOUT_DAYS = 365

_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbose": -1,
}


def _recall_at_k(
    scores: np.ndarray, y: np.ndarray, show_ids: np.ndarray, k: int = TOPK
) -> float:
    recalls = []
    for sid in np.unique(show_ids):
        m = show_ids == sid
        yy = y[m]
        if yy.sum() == 0:
            continue
        order = np.argsort(-scores[m])
        topk = set(order[:k].tolist())
        hit = sum(1 for j in np.where(yy == 1)[0] if j in topk)
        recalls.append(hit / yy.sum())
    return float(np.mean(recalls)) if recalls else 0.0


def train_inclusion(
    db_path: Path,
    out_path: Path,
    holdout_days: int = DEFAULT_HOLDOUT_DAYS,
    num_boost_round: int = 300,
    warmup_shows: int = 50,
) -> dict:
    conn = sqlite3.connect(db_path)
    X, y, dates, show_ids = build_training_data(conn, warmup_shows=warmup_shows)
    if len(y) == 0:
        raise ValueError(
            "no training rows — dataset smaller than warmup_shows "
            f"({warmup_shows})"
        )

    latest = int(dates.max())
    cutoff = latest - holdout_days
    train_mask = dates < cutoff
    test_mask = ~train_mask

    p12_idx = INCLUSION_FEATURE_COLUMNS.index("plays_last_12mo")

    dtrain = lgb.Dataset(
        X[train_mask], label=y[train_mask], feature_name=INCLUSION_FEATURE_COLUMNS
    )
    booster = lgb.train(_PARAMS, dtrain, num_boost_round=num_boost_round)

    pred = booster.predict(X[test_mask])
    model_recall = _recall_at_k(pred, y[test_mask], show_ids[test_mask])
    base_recall = _recall_at_k(
        X[test_mask][:, p12_idx], y[test_mask], show_ids[test_mask]
    )

    # Retrain on ALL data for the shipped artifact (holdout was for eval only).
    dall = lgb.Dataset(X, label=y, feature_name=INCLUSION_FEATURE_COLUMNS)
    ship = lgb.train(_PARAMS, dall, num_boost_round=num_boost_round)
    save_model_artifact(out_path, ship, INCLUSION_FEATURE_COLUMNS)

    gain = ship.feature_importance(importance_type="gain")
    importance = dict(
        sorted(
            zip(INCLUSION_FEATURE_COLUMNS, (float(g) for g in gain), strict=True),
            key=lambda kv: -kv[1],
        )
    )
    return {
        "trained_at": date.fromordinal(latest).isoformat(),
        "n_rows": int(len(y)),
        "n_train": int(train_mask.sum()),
        "n_holdout": int(test_mask.sum()),
        "n_holdout_shows": int(len(np.unique(show_ids[test_mask]))),
        "recall_at_25": round(model_recall, 4),
        "baseline_recall_at_25": round(base_recall, 4),
        "lift_over_baseline": round(model_recall / base_recall, 2) if base_recall else None,
        "feature_importance_gain": importance,
        "artifact": str(out_path),
    }
