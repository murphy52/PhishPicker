"""One-shot experiments.

`era_ab_experiment` — carry-forward §3 of the walking-skeleton plan.
Recency weighting and the era feature can double-count drift. We run
walk-forward with and without the recency weight, then ship the simpler
variant (era-only) unless the weighted arm beats it by ≥0.01 MRR.

The decision rule is deliberately a fixed threshold rather than a p-value:
the walk-forward samples overlap across arms, so a proper significance test
would need paired resampling. The threshold is a pragmatic stand-in.
"""

import sqlite3

from phishpicker.train.eval import walk_forward_eval

MIN_MRR_IMPROVEMENT = 0.01


def era_ab_experiment(
    conn: sqlite3.Connection,
    n_holdout_shows: int = 20,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    num_iterations: int = 300,
    seed: int = 0,
) -> dict:
    era_only = walk_forward_eval(
        conn,
        n_holdout_shows=n_holdout_shows,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        num_iterations=num_iterations,
        half_life_years=None,  # disable recency weighting
        seed=seed,
    )
    era_plus_recency = walk_forward_eval(
        conn,
        n_holdout_shows=n_holdout_shows,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        num_iterations=num_iterations,
        half_life_years=7.0,
        seed=seed,
    )

    def summary(r):
        return {
            "top1": r.top1,
            "top5": r.top5,
            "top20": r.top20,
            "mrr": r.mrr,
            "mrr_ci": list(r.mrr_ci),
            "n_slots": r.n_slots,
        }

    verdict = (
        "ship_era_plus_recency"
        if era_plus_recency.mrr - era_only.mrr >= MIN_MRR_IMPROVEMENT
        else "ship_era_only"
    )
    return {
        "era_only": summary(era_only),
        "era_plus_recency": summary(era_plus_recency),
        "mrr_delta": era_plus_recency.mrr - era_only.mrr,
        "verdict": verdict,
    }
