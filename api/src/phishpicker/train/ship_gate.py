"""Ship gate: block a training run whose model is worse than the one it replaces.

`check_against_current_model` grades the current model (by default the
`model.lgb` in the data dir, the artifact the run would replace) with
`evaluate_booster`, the code behind `phishpicker train eval-model`, on the
same holdout shows the new model was graded on. The new model passes only if
its MRR is level with or better than the current model's on those shows.

Two things keep that comparison like for like:
- Same shows. The previous metrics.json was graded on whatever the last N
  shows were when it was trained. Comparing against it let v12 (MRR 0.152 on
  the summer holdout) pass against v11's April 0.143, though v11 scored 0.159
  on the summer shows (issue #40).
- Shows neither model trained on. A model graded on shows it trained on looks
  far better than it is: v11 scores MRR 0.238 on its own April holdout, which
  it trained on, against 0.143 walk-forward. The current model's training
  cutoff comes from the metrics.json beside it; holdout shows before that
  cutoff are left out for both models.

When the current model can't be graded (missing, unreadable, a different
feature set, or it trained on every holdout show), the gate falls back to
`ship_gate_check`, the old comparison with the previous metrics.json MRR and
its 0.02 tolerance, and says that number came from different shows. With
neither a model nor a metrics.json (first ship) it passes. Override is an
explicit caller choice — this module just returns a decision.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

import lightgbm as lgb
from lightgbm.basic import LightGBMError

from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.eval import FoldResult, WalkForwardResult, evaluate_booster
from phishpicker.train.features import FEATURE_COLUMNS
from phishpicker.train.metrics import mrr as mrr_fn

# Same shows, neither model trained on them: no holdout-to-holdout noise to
# allow for, so the new model has to be level or better (the retrain policy:
# promote only if flat or better).
SAME_HOLDOUT_MAX_DROP = 0.0
# Different holdouts: the original slack for show-to-show noise.
PREVIOUS_METRICS_MAX_DROP = 0.02


@dataclass(frozen=True)
class GateDecision:
    """What the gate compared and why it passed or blocked. The holdout fields
    describe the shows the decision was made on."""

    passed: bool
    basis: str  # "same_holdout" | "previous_metrics" | "no_baseline"
    candidate_mrr: float
    current_mrr: float | None  # the current model on the same shows
    previous_metrics_mrr: float | None  # the fallback: a different holdout
    max_drop: float | None
    current_model_path: str
    holdout_n_shows: int
    holdout_first_date: str | None
    holdout_last_date: str | None
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def check_against_current_model(
    conn: sqlite3.Connection,
    candidate: WalkForwardResult,
    current_model_path: Path,
    n_holdout_shows: int,
    max_drop: float = SAME_HOLDOUT_MAX_DROP,
) -> GateDecision:
    """Compare the new run's walk-forward result with the current model graded
    on the same holdout shows. `current_model_path` is a model.lgb with its
    .meta.json, and the metrics.json from the run that trained it, beside it."""
    model_path = Path(current_model_path)
    metrics_path = model_path.with_name("metrics.json")
    previous = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
    folds = candidate.fold_results

    booster, problem = _load_current(model_path)
    if booster is None:
        return _fallback(candidate, model_path, metrics_path, previous, problem)

    cutoff = (previous or {}).get("cutoff_date")
    if cutoff:
        # It trained on every show strictly before its cutoff.
        compared = [f for f in folds if f.heldout_show_date >= cutoff]
        n_seen = len(folds) - len(compared)
        if not compared:
            why = (
                f"the current model at {model_path} trained on all {len(folds)} "
                f"holdout shows (its cutoff is {cutoff})"
            )
            return _fallback(candidate, model_path, metrics_path, previous, why)
        caveat = (
            f"; the current model trained on {n_seen} of {len(folds)} holdout shows "
            f"(cutoff {cutoff}), so they're left out"
            if n_seen
            else ""
        )
    else:
        compared = folds
        caveat = (
            f"; the current model's training cutoff is unknown (no cutoff_date in "
            f"{metrics_path}), so if it trained on some of these shows its MRR is flattered"
        )

    try:
        current = evaluate_booster(
            conn,
            booster,
            n_holdout_shows=n_holdout_shows,
            show_ids={f.heldout_show_id for f in compared},
        )
    except LightGBMError as exc:  # e.g. a booster that disagrees with its .meta.json
        why = f"can't grade the current model at {model_path} ({exc})"
        return _fallback(candidate, model_path, metrics_path, previous, why)
    if len(compared) == len(folds):
        candidate_mrr = candidate.mrr
    else:
        candidate_mrr = mrr_fn([rank for f in compared for rank in f.ranks])
    passed = candidate_mrr >= current.mrr - max_drop
    verdict = (
        "PASS" if passed else f"BLOCK: the candidate needs at least {current.mrr - max_drop:.4f}"
    )
    return _decision(
        compared,
        passed=passed,
        basis="same_holdout",
        candidate_mrr=candidate_mrr,
        current_mrr=current.mrr,
        max_drop=max_drop,
        model_path=model_path,
        summary=(
            f"ship gate: candidate MRR {candidate_mrr:.4f} vs current {current.mrr:.4f} "
            f"on the same {_describe(compared)}{caveat}. Current model: {model_path}. "
            f"{verdict}."
        ),
    )


def ship_gate_check(
    new_mrr: float,
    previous_metrics_path: Path,
    max_drop: float = PREVIOUS_METRICS_MAX_DROP,
) -> bool:
    """The fallback: the new MRR must stay within `max_drop` of the previous
    run's metrics.json MRR. That number was graded on that run's holdout, not
    this one's. A missing file (first ship) passes."""
    path = Path(previous_metrics_path)
    if not path.exists():
        return True
    prev = json.loads(path.read_text())
    prev_mrr = float(prev.get("mrr", 0.0))
    return new_mrr >= prev_mrr - max_drop


def _load_current(path: Path) -> tuple[lgb.Booster | None, str]:
    """The current model's booster, or None and the reason it can't be graded."""
    if not path.exists():
        return None, f"no current model at {path}"
    try:
        scorer = LightGBMScorer.load(path)
        scorer.assert_compatible_with(FEATURE_COLUMNS)
    except (OSError, ValueError, KeyError, LightGBMError) as exc:
        return None, f"can't grade the current model at {path} ({exc})"
    return scorer.booster, ""


def _fallback(
    candidate: WalkForwardResult,
    model_path: Path,
    metrics_path: Path,
    previous: dict | None,
    why: str,
) -> GateDecision:
    folds = candidate.fold_results
    if previous is None:
        return _decision(
            folds,
            passed=True,
            basis="no_baseline",
            candidate_mrr=candidate.mrr,
            max_drop=None,
            model_path=model_path,
            summary=f"ship gate: {why}, and no {metrics_path}; nothing to compare against. PASS.",
        )
    previous_mrr = float(previous.get("mrr", 0.0))
    passed = ship_gate_check(candidate.mrr, metrics_path, max_drop=PREVIOUS_METRICS_MAX_DROP)
    return _decision(
        folds,
        passed=passed,
        basis="previous_metrics",
        candidate_mrr=candidate.mrr,
        previous_metrics_mrr=previous_mrr,
        max_drop=PREVIOUS_METRICS_MAX_DROP,
        model_path=model_path,
        summary=(
            f"ship gate: {why}. Fallback: candidate MRR {candidate.mrr:.4f} on "
            f"{_describe(folds)} vs {previous_mrr:.4f} in {metrics_path}, graded on that "
            f"run's own holdout, likely different shows (tolerance {PREVIOUS_METRICS_MAX_DROP}). "
            f"{'PASS' if passed else 'BLOCK'}."
        ),
    )


def _decision(
    folds: list[FoldResult],
    *,
    passed: bool,
    basis: str,
    candidate_mrr: float,
    max_drop: float | None,
    model_path: Path,
    summary: str,
    current_mrr: float | None = None,
    previous_metrics_mrr: float | None = None,
) -> GateDecision:
    dates = sorted(f.heldout_show_date for f in folds)
    return GateDecision(
        passed=passed,
        basis=basis,
        candidate_mrr=candidate_mrr,
        current_mrr=current_mrr,
        previous_metrics_mrr=previous_metrics_mrr,
        max_drop=max_drop,
        current_model_path=str(model_path),
        holdout_n_shows=len(folds),
        holdout_first_date=dates[0] if dates else None,
        holdout_last_date=dates[-1] if dates else None,
        summary=summary,
    )


def _describe(folds: list[FoldResult]) -> str:
    dates = sorted(f.heldout_show_date for f in folds)
    if not dates:
        return "0 holdout shows"
    return f"{len(dates)} holdout shows ({dates[0]} to {dates[-1]})"
