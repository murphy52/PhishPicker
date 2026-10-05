"""Serving for the show-level inclusion model — the "Likely Tonight" list.

Given an upcoming show, returns songs ranked by P(appears anywhere tonight).
Independent of the slot-level next-song ranker; loaded from its own artifact.

The raw model chance goes through two adjustments so the numbers can be
taken at face value (e.g. to price a bonus pick):

1. Run rule: a song already played earlier in this run (same venue + tour)
   is capped at RUN_REPEAT_CHANCE — Phish almost never repeats within a run,
   and the model has no feature that knows it.
2. Calibration (optional): a monotone isotonic mapping fitted on walk-forward
   out-of-sample predictions, saved next to the model as
   `inclusion_calibration.json`. It is only used with the exact model file it
   was fitted for (sha256); absent or mismatched, chances are served raw.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    InclusionHistory,
)

log = logging.getLogger(__name__)

# Measured: of 1,686 songs already played earlier in a run (73 shows,
# Jun 2025 - Oct 2026), 3 came back later in the same run — 0.18%.
RUN_REPEAT_CHANCE = 0.002

# Calibrated chances are kept inside this range: never a flat 0% (bustouts
# happen) and never a sure thing.
CALIBRATED_MIN = 0.001
CALIBRATED_MAX = 0.95

CALIBRATION_FILENAME = "inclusion_calibration.json"


def load_inclusion_scorer(path: Path) -> LightGBMScorer:
    scorer = LightGBMScorer.load(path)
    scorer.assert_compatible_with(INCLUSION_FEATURE_COLUMNS)
    return scorer


def apply_run_rule(probs: np.ndarray, already_played: np.ndarray) -> np.ndarray:
    """Cap the chance of songs already played earlier in this run (never raises one)."""
    p = np.asarray(probs, dtype=float)
    return np.where(np.asarray(already_played, dtype=bool), np.minimum(p, RUN_REPEAT_CHANCE), p)


@dataclass(frozen=True)
class InclusionCalibration:
    """Monotone piecewise-linear map from run-rule-adjusted chance to calibrated chance."""

    x: tuple[float, ...]
    y: tuple[float, ...]
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        x, y = np.asarray(self.x, dtype=float), np.asarray(self.y, dtype=float)
        if x.ndim != 1 or x.shape != y.shape or len(x) == 0:
            raise ValueError("calibration x and y must be equal-length, non-empty lists")
        if np.any(np.diff(x) < 0) or np.any(np.diff(y) < 0):
            raise ValueError("calibration mapping must be non-decreasing")
        if x.min() < 0 or x.max() > 1 or y.min() < 0 or y.max() > 1:
            raise ValueError("calibration values must be probabilities")

    def apply(self, probs: np.ndarray) -> np.ndarray:
        mapped = np.interp(np.asarray(probs, dtype=float), self.x, self.y)
        return np.clip(mapped, CALIBRATED_MIN, CALIBRATED_MAX)

    def to_dict(self) -> dict:
        return {**self.meta, "x": list(self.x), "y": list(self.y)}

    @classmethod
    def from_dict(cls, data: dict) -> InclusionCalibration:
        meta = {k: v for k, v in data.items() if k not in ("x", "y")}
        return cls(x=tuple(data["x"]), y=tuple(data["y"]), meta=meta)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_inclusion_calibration(path: Path, model_path: Path) -> InclusionCalibration | None:
    """The calibration for `model_path`, or None when absent, unreadable, or
    fitted for a different model file (serving then falls back to raw chances)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        cal = InclusionCalibration.from_dict(json.loads(path.read_text()))
    except (ValueError, KeyError, TypeError):
        log.exception("unreadable inclusion calibration at %s; serving raw chances", path)
        return None
    if cal.meta.get("model_sha256") != file_sha256(model_path):
        log.warning(
            "inclusion calibration %s was fitted for a different model; serving raw chances",
            path,
        )
        return None
    return cal


def likely_tonight(
    read_conn: sqlite3.Connection,
    show_id: int,
    scorer: LightGBMScorer,
    top_n: int = 30,
    calibration: InclusionCalibration | None = None,
) -> list[dict]:
    """Ranked inclusion predictions for `show_id` (must exist in `shows`)."""
    hist = InclusionHistory(read_conn)
    try:
        ctx = hist.context_for(show_id)
    except KeyError:
        return []

    sids = hist.candidate_ids(ctx.show_date)
    X, kept = hist.feature_matrix(ctx, sids)
    if not kept:
        return []

    played_this_run = hist.run_prior_songs(show_id)
    adjusted = apply_run_rule(scorer.score(X), np.array([s in played_this_run for s in kept]))
    shown = calibration.apply(adjusted) if calibration is not None else adjusted
    # Calibration ties songs (it is a step-ish map); the adjusted score breaks ties.
    order = sorted(range(len(kept)), key=lambda i: (-shown[i], -adjusted[i]))[:top_n]

    top_ids = [kept[i] for i in order]
    names = dict(
        read_conn.execute(
            f"SELECT song_id, name FROM songs WHERE song_id IN ({','.join('?' * len(top_ids))})",
            top_ids,
        ).fetchall()
    )
    return [
        {
            "song_id": kept[i],
            "name": names.get(kept[i], str(kept[i])),
            "probability": round(float(shown[i]), 4),
        }
        for i in order
    ]
