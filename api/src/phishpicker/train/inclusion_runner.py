"""Train + evaluate + ship the show-level inclusion model.

Produces `inclusion_model.lgb` (+ `.meta.json`) alongside the slot-ranker
`model.lgb`. Evaluation reports Recall@K vs a plays_last_12mo frequency
baseline on a time-based holdout — the spike's headline metric.

Also fits the serving calibration (`inclusion_calibration.json`): walk forward
over the last year — train on everything before a block of shows, predict
the block, step on — apply the run rule, and fit isotonic regression on those
out-of-sample chances. The file records the sha256 of the model it ships with.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np

from phishpicker.inclusion import (
    CALIBRATED_MAX,
    CALIBRATED_MIN,
    CALIBRATION_FILENAME,
    RUN_REPEAT_CHANCE,
    InclusionCalibration,
    apply_run_rule,
    file_sha256,
)
from phishpicker.model.lightgbm_scorer import save_model_artifact
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    InclusionHistory,
    InclusionRows,
    build_inclusion_rows,
    played_earlier_in_run,
)

TOPK = 25
DEFAULT_HOLDOUT_DAYS = 365
# Walk-forward block: retrain, then predict the next 10 shows (about a tour
# leg — matches the 2-4x/year retrain cadence better than per-show refits).
DEFAULT_BLOCK_SHOWS = 10
# Calibration is fitted on the walk-forward chances of the last year of shows.
DEFAULT_CALIBRATION_DAYS = 365

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


def fit_inclusion_booster(
    X: np.ndarray, y: np.ndarray, num_boost_round: int = 300
) -> lgb.Booster:
    """Fit the inclusion model with the production params."""
    data = lgb.Dataset(X, label=y, feature_name=INCLUSION_FEATURE_COLUMNS)
    return lgb.train(_PARAMS, data, num_boost_round=num_boost_round)


@dataclass(frozen=True)
class WalkForward:
    """Out-of-sample chances: each block predicted by a model trained only on
    shows dated before the block's first show."""

    rows_idx: np.ndarray  # indices into the InclusionRows
    raw: np.ndarray
    adjusted: np.ndarray  # raw with the run rule applied
    block: np.ndarray  # block number per prediction
    blocks: list[dict]


def walk_forward(
    rows: InclusionRows,
    run_flags: np.ndarray,
    start_ord: int,
    end_ord: int | None = None,
    block_shows: int = DEFAULT_BLOCK_SHOWS,
    num_boost_round: int = 300,
    breaks: tuple[int, ...] = (),
) -> WalkForward:
    """Walk forward over shows dated in [start_ord, end_ord) in blocks of
    `block_shows`; a date in `breaks` always starts a new block. Blocks with
    no earlier training data are skipped."""
    in_range = rows.dates >= start_ord
    if end_ord is not None:
        in_range &= rows.dates < end_ord
    show_date = dict(
        zip(rows.show_ids[in_range].tolist(), rows.dates[in_range].tolist(), strict=True)
    )
    ordered = sorted(show_date, key=lambda s: (show_date[s], s))

    cuts = sorted(breaks)
    segments: list[list[int]] = [[]]
    ci = 0
    for sid in ordered:
        while ci < len(cuts) and show_date[sid] >= cuts[ci]:
            if segments[-1]:
                segments.append([])
            ci += 1
        segments[-1].append(sid)
    chunks = [seg[i : i + block_shows] for seg in segments for i in range(0, len(seg), block_shows)]

    idx_parts, raw_parts, block_parts, blocks = [], [], [], []
    for chunk in chunks:
        start = show_date[chunk[0]]
        train = rows.dates < start
        if not train.any():
            continue
        idx = np.where(np.isin(rows.show_ids, chunk))[0]
        booster = fit_inclusion_booster(rows.X[train], rows.y[train], num_boost_round)
        raw_parts.append(booster.predict(rows.X[idx]))
        idx_parts.append(idx)
        block_parts.append(np.full(len(idx), len(blocks)))
        blocks.append(
            {
                "start": date.fromordinal(start).isoformat(),
                "end": date.fromordinal(show_date[chunk[-1]]).isoformat(),
                "start_ord": start,
                "n_shows": len(chunk),
                "trained_through": date.fromordinal(int(rows.dates[train].max())).isoformat(),
            }
        )
    if not blocks:
        empty = np.array([], dtype=int)
        return WalkForward(empty, np.array([]), np.array([]), empty, [])
    rows_idx = np.concatenate(idx_parts)
    raw = np.concatenate(raw_parts)
    return WalkForward(
        rows_idx=rows_idx,
        raw=raw,
        adjusted=apply_run_rule(raw, run_flags[rows_idx]),
        block=np.concatenate(block_parts),
        blocks=blocks,
    )


def fit_isotonic(probs: np.ndarray, y: np.ndarray) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(x, y) knots of a monotone isotonic fit of outcomes on chances."""
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(np.asarray(probs, dtype=float), np.asarray(y, dtype=float))
    return (
        tuple(float(v) for v in iso.X_thresholds_),
        tuple(float(v) for v in iso.y_thresholds_),
    )


def build_calibration(
    rows: InclusionRows,
    run_flags: np.ndarray,
    calibration_days: int = DEFAULT_CALIBRATION_DAYS,
    block_shows: int = DEFAULT_BLOCK_SHOWS,
    num_boost_round: int = 300,
) -> InclusionCalibration | None:
    """Isotonic calibration fitted on walk-forward, run-rule-adjusted chances
    for the last `calibration_days` of shows. None if nothing could be predicted."""
    latest = int(rows.dates.max())
    wf = walk_forward(
        rows, run_flags, latest - calibration_days, block_shows=block_shows,
        num_boost_round=num_boost_round,
    )
    if not len(wf.raw):
        return None
    x, y = fit_isotonic(wf.adjusted, rows.y[wf.rows_idx])
    dates = rows.dates[wf.rows_idx]
    return InclusionCalibration(
        x=x,
        y=y,
        meta={
            "kind": "isotonic",
            "fit_from": date.fromordinal(int(dates.min())).isoformat(),
            "fit_through": date.fromordinal(int(dates.max())).isoformat(),
            "n_predictions": len(wf.raw),
            "n_played": int(rows.y[wf.rows_idx].sum()),
            "n_shows": len(np.unique(rows.show_ids[wf.rows_idx])),
            "n_blocks": len(wf.blocks),
            "block_shows": block_shows,
            "calibration_days": calibration_days,
            "num_boost_round": num_boost_round,
            "run_repeat_chance": RUN_REPEAT_CHANCE,
            "calibrated_range": [CALIBRATED_MIN, CALIBRATED_MAX],
        },
    )


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
    calibrate: bool = True,
    calibration_days: int = DEFAULT_CALIBRATION_DAYS,
    block_shows: int = DEFAULT_BLOCK_SHOWS,
) -> dict:
    conn = sqlite3.connect(db_path)
    hist = InclusionHistory(conn)
    rows = build_inclusion_rows(hist, warmup_shows=warmup_shows)
    X, y, dates, show_ids = rows.X, rows.y, rows.dates, rows.show_ids
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

    booster = fit_inclusion_booster(X[train_mask], y[train_mask], num_boost_round)

    pred = booster.predict(X[test_mask])
    model_recall = _recall_at_k(pred, y[test_mask], show_ids[test_mask])
    base_recall = _recall_at_k(
        X[test_mask][:, p12_idx], y[test_mask], show_ids[test_mask]
    )

    # Retrain on ALL data for the shipped artifact (holdout was for eval only).
    ship = fit_inclusion_booster(X, y, num_boost_round)
    save_model_artifact(out_path, ship, INCLUSION_FEATURE_COLUMNS)

    calibration = None
    if calibrate:
        flags = played_earlier_in_run(hist, rows.show_ids, rows.song_ids)
        cal = build_calibration(rows, flags, calibration_days, block_shows, num_boost_round)
        if cal is not None:
            meta = {
                **cal.meta,
                "model_trained_through": date.fromordinal(latest).isoformat(),
                "model_sha256": file_sha256(out_path),
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            cal_path = Path(out_path).parent / CALIBRATION_FILENAME
            cal_path.write_text(json.dumps({**meta, "x": list(cal.x), "y": list(cal.y)}))
            calibration = {**meta, "n_knots": len(cal.x), "path": str(cal_path)}

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
        "calibration": calibration,
    }
