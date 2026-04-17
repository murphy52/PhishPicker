"""Metrics and bootstrap CIs for walk-forward evaluation.

Per carry-forward §1: walk-forward n≈400 → Top-1 CI ±2.7pp. Point estimates
alone don't capture this, so every metric ships with a 95% bootstrap CI.

Per carry-forward §6: per-slot breakdown — opener prediction is structurally
easier than mid-set-2. Collapsing into one number hides the hard cases.
"""

import random
from collections.abc import Callable


def topk_hit_rate(ranks: list[int], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r <= k) / len(ranks)


def mrr(ranks: list[int]) -> float:
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks) / len(ranks)


def bootstrap_ci(
    ranks: list[int],
    metric_fn: Callable[[list[int]], float],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap 95% CI (or other confidence) on a scalar metric.

    Resamples ranks with replacement `n_resamples` times, computes the metric
    on each resample, returns the (confidence)th percentile bounds.
    """
    if not ranks:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(ranks)
    samples: list[float] = []
    for _ in range(n_resamples):
        resample = [ranks[rng.randrange(n)] for _ in range(n)]
        samples.append(metric_fn(resample))
    samples.sort()
    tail = (1.0 - confidence) / 2.0
    lo = samples[int(tail * n_resamples)]
    hi = samples[int((1.0 - tail) * n_resamples) - 1]
    return lo, hi


def by_slot_position(ranks: list[int], slot_positions: list[int]) -> dict[int, dict[str, float]]:
    """Group ranks by slot index (1=opener, etc.) and compute Top-1/5 + MRR."""
    if len(ranks) != len(slot_positions):
        raise ValueError("ranks and slot_positions must be same length")
    by_slot: dict[int, list[int]] = {}
    for r, s in zip(ranks, slot_positions, strict=True):
        by_slot.setdefault(s, []).append(r)
    return {
        slot: {
            "top1": topk_hit_rate(rs, 1),
            "top5": topk_hit_rate(rs, 5),
            "mrr": mrr(rs),
            "n": float(len(rs)),
        }
        for slot, rs in by_slot.items()
    }
