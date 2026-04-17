import pytest

from phishpicker.train.metrics import (
    bootstrap_ci,
    by_slot_position,
    mrr,
    topk_hit_rate,
)


def test_topk_hit_rate_counts_ranks_at_or_below_k():
    assert topk_hit_rate([1, 2, 3, 100], k=1) == pytest.approx(0.25)
    assert topk_hit_rate([1, 2, 3, 100], k=5) == pytest.approx(0.75)
    assert topk_hit_rate([], k=1) == 0.0


def test_mrr_is_mean_reciprocal_rank():
    assert mrr([1]) == pytest.approx(1.0)
    assert mrr([1, 2]) == pytest.approx((1.0 + 0.5) / 2)
    assert mrr([]) == 0.0


def test_bootstrap_ci_returns_ordered_bounds():
    ranks = [1, 2, 3, 4, 5] * 20  # 100 values
    lo, hi = bootstrap_ci(ranks, lambda rs: topk_hit_rate(rs, k=3), n_resamples=200, seed=0)
    assert lo <= hi
    assert 0.0 <= lo <= 1.0
    assert 0.0 <= hi <= 1.0


def test_bootstrap_ci_brackets_the_point_estimate_on_typical_samples():
    ranks = [1, 2, 3, 4, 5] * 20
    point = topk_hit_rate(ranks, k=3)  # 0.6
    lo, hi = bootstrap_ci(ranks, lambda rs: topk_hit_rate(rs, k=3), n_resamples=500, seed=0)
    # 95% CI should bracket the point on a symmetric distribution.
    assert lo - 0.1 <= point <= hi + 0.1


def test_by_slot_position_groups_ranks_by_slot():
    ranks = [1, 2, 100, 1, 2, 100]
    slots = [1, 2, 3, 1, 2, 3]
    out = by_slot_position(ranks, slots)
    assert set(out.keys()) == {1, 2, 3}
    assert out[1]["top1"] == pytest.approx(1.0)
    assert out[3]["top1"] == pytest.approx(0.0)


def test_bootstrap_ci_empty_input_returns_zero_range():
    lo, hi = bootstrap_ci([], lambda rs: mrr(rs), n_resamples=10, seed=0)
    assert lo == 0.0
    assert hi == 0.0
