import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SongStats:
    song_id: int
    times_played_last_12mo: int
    total_plays_ever: int
    shows_since_last_played_anywhere: int | None  # None = never played
    shows_since_last_played_here: int | None
    played_already_this_run: bool
    opener_score: float  # expected [0.0, 1.0]
    encore_score: float  # expected [0.0, 1.0]
    middle_score: float  # expected [0.0, 1.0]

    def __post_init__(self) -> None:
        for name in ("opener_score", "encore_score", "middle_score"):
            v = getattr(self, name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {v}")


@dataclass(frozen=True)
class Context:
    current_set: str  # '1','2','3','E'
    current_position: int  # next slot we're filling (1 = opener)


def base_rate(times_played_last_12mo: int, total_plays_ever: int) -> float:
    # 0.2 floor keeps bust-out candidates (n_12mo=0) alive
    return 0.2 + math.log1p(times_played_last_12mo) + 0.3 * math.log1p(total_plays_ever)


def recency_multiplier(shows_since_last: int | None) -> float:
    if shows_since_last is None:
        return 1.0
    # 0.05 floor — never zero out signal entirely
    return 0.05 + 0.95 * (1.0 - math.exp(-shows_since_last / 30.0))


def venue_multiplier(shows_since_last_here: int | None) -> float:
    if shows_since_last_here is None:
        return 1.2
    return 1.0 + 0.5 * (1.0 - math.exp(-shows_since_last_here / 20.0))


def run_multiplier(played_already_this_run: bool) -> float:
    return 0.05 if played_already_this_run else 1.0


def role_fit(stats: SongStats, ctx: Context) -> float:
    if ctx.current_set == "E":
        return 0.2 + stats.encore_score
    if ctx.current_set == "1" and ctx.current_position == 1:
        return 0.2 + stats.opener_score
    return 0.3 + 0.7 * stats.middle_score


def score(stats: SongStats, ctx: Context) -> float:
    raw = (
        base_rate(stats.times_played_last_12mo, stats.total_plays_ever)
        * recency_multiplier(stats.shows_since_last_played_anywhere)
        * venue_multiplier(stats.shows_since_last_played_here)
        * run_multiplier(stats.played_already_this_run)
        * role_fit(stats, ctx)
    )
    return max(0.0, raw)
