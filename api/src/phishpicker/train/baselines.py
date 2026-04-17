"""Baseline scorers for walk-forward comparison.

Each Scorer is a callable ``(conn, cutoff_date, show_date, venue_id, played,
current_set, candidates) -> np.ndarray``. `evaluate_scorer` runs the same
walk-forward loop as train.eval but swaps the LightGBM booster for the
scorer — no training is required for a baseline.
"""

import random
import sqlite3
from collections.abc import Callable

import numpy as np

from phishpicker.model.heuristic import Context
from phishpicker.model.heuristic import score as heuristic_score
from phishpicker.model.stats import compute_song_stats
from phishpicker.train.eval import FoldResult, WalkForwardResult

Scorer = Callable[
    [sqlite3.Connection, str, str, int | None, list[int], str, list[int]],
    np.ndarray,
]


def random_scorer(seed: int = 0) -> Scorer:
    rng = random.Random(seed)

    def _f(conn, cutoff_date, show_date, venue_id, played, current_set, candidates):
        return np.array([rng.random() for _ in candidates])

    return _f


def frequency_scorer(_conn_unused: sqlite3.Connection | None = None) -> Scorer:
    """Frequency-only: score = plays-before-cutoff count. The `conn` passed
    to the outer factory is unused — we re-query inside to stay cutoff-safe.
    """

    def _f(conn, cutoff_date, show_date, venue_id, played, current_set, candidates):
        if not candidates:
            return np.array([])
        placeholders = ",".join("?" * len(candidates))
        counts = dict(
            conn.execute(
                f"""
                SELECT ss.song_id, COUNT(*) AS n
                FROM setlist_songs ss JOIN shows s USING (show_id)
                WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
                GROUP BY ss.song_id
                """,
                [*candidates, cutoff_date],
            ).fetchall()
        )
        return np.array([float(counts.get(sid, 0)) for sid in candidates])

    return _f


def heuristic_scorer() -> Scorer:
    """Wraps phishpicker.model.heuristic.score so it fits the Scorer protocol."""

    def _f(conn, cutoff_date, show_date, venue_id, played, current_set, candidates):
        stats = compute_song_stats(conn, show_date, venue_id, candidates)
        ctx = Context(current_set=current_set, current_position=len(played) + 1)
        return np.array([heuristic_score(stats[sid], ctx) for sid in candidates])

    return _f


def evaluate_scorer(
    conn: sqlite3.Connection,
    scorer: Scorer,
    n_holdout_shows: int = 20,
) -> WalkForwardResult:
    holdout = conn.execute(
        "SELECT show_id, show_date, venue_id FROM shows "
        "ORDER BY show_date DESC, show_id DESC LIMIT ?",
        (n_holdout_shows,),
    ).fetchall()
    holdout = list(reversed(holdout))
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]

    fold_results: list[FoldResult] = []
    all_ranks: list[int] = []

    for sh in holdout:
        cutoff = sh["show_date"]
        setlist = conn.execute(
            "SELECT set_number, position, song_id FROM setlist_songs "
            "WHERE show_id = ? ORDER BY set_number, position",
            (sh["show_id"],),
        ).fetchall()
        played: list[int] = []
        fold = FoldResult(
            heldout_show_id=int(sh["show_id"]),
            heldout_show_date=cutoff,
            train_cutoff_date=cutoff,
        )
        for r in setlist:
            positive = int(r["song_id"])
            pool = [s for s in all_song_ids if s not in played]
            scores = scorer(conn, cutoff, cutoff, sh["venue_id"], played, r["set_number"], pool)
            order = np.argsort(-scores)
            rank = int(np.where([pool[i] == positive for i in order])[0][0]) + 1
            fold.ranks.append(rank)
            all_ranks.append(rank)
            played.append(positive)
        for k in (1, 5, 20):
            fold.top_k_hits[k] = sum(1 for rk in fold.ranks if rk <= k) / max(1, len(fold.ranks))
        fold_results.append(fold)

    def topk(k: int) -> float:
        if not all_ranks:
            return 0.0
        return sum(1 for rk in all_ranks if rk <= k) / len(all_ranks)

    mrr = float(np.mean([1.0 / r for r in all_ranks])) if all_ranks else 0.0
    return WalkForwardResult(
        fold_results=fold_results,
        top1=topk(1),
        top5=topk(5),
        top20=topk(20),
        mrr=mrr,
        n_slots=len(all_ranks),
    )
