import pytest

from phishpicker.model.heuristic import (
    Context,
    SongStats,
    base_rate,
    recency_multiplier,
    role_fit,
    run_multiplier,
    score,
    venue_multiplier,
)


def _stats(**kwargs) -> SongStats:
    defaults = {
        "song_id": 1,
        "times_played_last_12mo": 5,
        "total_plays_ever": 20,
        "shows_since_last_played_anywhere": 50,
        "shows_since_last_played_here": None,
        "played_already_this_run": False,
        "opener_score": 0.5,
        "encore_score": 0.3,
        "middle_score": 0.5,
    }
    return SongStats(**{**defaults, **kwargs})


def test_base_rate_floor():
    assert base_rate(times_played_last_12mo=0, total_plays_ever=0) == pytest.approx(0.2)


def test_base_rate_higher_for_more_played_song():
    assert base_rate(times_played_last_12mo=0, total_plays_ever=0) < base_rate(
        times_played_last_12mo=20, total_plays_ever=20
    )


def test_recency_multiplier_small_when_recently_played():
    assert recency_multiplier(shows_since_last=1) < recency_multiplier(shows_since_last=100)


def test_recency_multiplier_none_is_neutral():
    # never-played treated as neutral (not a boost or penalty)
    assert recency_multiplier(shows_since_last=None) == pytest.approx(1.0)


def test_venue_multiplier_none_gives_boost():
    assert venue_multiplier(shows_since_last_here=None) == pytest.approx(1.2)


def test_venue_multiplier_recent_visit_no_boost():
    assert venue_multiplier(shows_since_last_here=0) == pytest.approx(1.0)


def test_run_multiplier_penalizes_repeats():
    assert run_multiplier(played_already_this_run=True) == pytest.approx(0.05)
    assert run_multiplier(played_already_this_run=False) == pytest.approx(1.0)


def test_role_fit_encore_uses_encore_score():
    ctx = Context(current_set="E", current_position=1)
    s = _stats(encore_score=0.8)
    assert role_fit(s, ctx) == pytest.approx(0.2 + 0.8)


def test_role_fit_opener_uses_opener_score():
    ctx = Context(current_set="1", current_position=1)
    s = _stats(opener_score=0.9)
    assert role_fit(s, ctx) == pytest.approx(0.2 + 0.9)


def test_role_fit_middle_slot():
    ctx = Context(current_set="2", current_position=3)
    s = _stats(middle_score=0.6)
    assert role_fit(s, ctx) == pytest.approx(0.3 + 0.7 * 0.6)


def test_score_orders_candidates_reasonably():
    stale_popular = _stats(
        song_id=1,
        times_played_last_12mo=0,
        total_plays_ever=30,
        shows_since_last_played_anywhere=200,
    )
    recently_played = _stats(
        song_id=2,
        times_played_last_12mo=15,
        total_plays_ever=40,
        shows_since_last_played_anywhere=2,
    )
    ctx = Context(current_set="2", current_position=3)
    assert score(stale_popular, ctx) > score(recently_played, ctx)


def test_score_run_penalty_propagates():
    normal = _stats(played_already_this_run=False)
    repeat = _stats(played_already_this_run=True)
    ctx = Context(current_set="2", current_position=3)
    assert score(repeat, ctx) < score(normal, ctx) * 0.1


def test_song_stats_rejects_out_of_range_scores():
    with pytest.raises(ValueError, match="opener_score"):
        _stats(opener_score=1.5)
    with pytest.raises(ValueError, match="encore_score"):
        _stats(encore_score=-0.1)
