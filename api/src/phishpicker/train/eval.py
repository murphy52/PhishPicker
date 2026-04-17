"""Walk-forward evaluation.

For each of the last N shows (reverse-chron), refit a LightGBM ranker on all
prior-show setlists, then score every slot of the held-out show. Metrics are
aggregated across all held-out slots.

Per carry-forward §4 (feature leakage): features that depend on tour/run state
(tour_position, times_this_tour, etc.) are recomputed from-scratch per fold.
That happens naturally here because build_feature_rows is called with
`show_date = heldout_show_date` and reads fresh DB rows.
"""

import sqlite3
from dataclasses import dataclass, field
from functools import partial

import numpy as np

from phishpicker.train.build import build_feature_rows
from phishpicker.train.metrics import (
    bootstrap_ci,
    by_slot_position,
    topk_hit_rate,
)
from phishpicker.train.metrics import (
    mrr as mrr_fn,
)
from phishpicker.train.trainer import train_ranker


@dataclass
class FoldResult:
    heldout_show_id: int
    heldout_show_date: str
    train_cutoff_date: str
    ranks: list[int] = field(default_factory=list)
    slot_positions: list[int] = field(default_factory=list)
    top_k_hits: dict[int, float] = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    fold_results: list[FoldResult]
    top1: float
    top5: float
    top20: float
    mrr: float
    n_slots: int
    top1_ci: tuple[float, float] = (0.0, 0.0)
    top5_ci: tuple[float, float] = (0.0, 0.0)
    top20_ci: tuple[float, float] = (0.0, 0.0)
    mrr_ci: tuple[float, float] = (0.0, 0.0)
    by_slot: dict[int, dict[str, float]] = field(default_factory=dict)


def walk_forward_eval(
    conn: sqlite3.Connection,
    n_holdout_shows: int = 20,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    num_iterations: int = 300,
    half_life_years: float | None = 7.0,
    seed: int = 0,
) -> WalkForwardResult:
    # Only hold out shows that actually have setlist data — phish.net lists
    # future-dated placeholder shows that haven't happened yet.
    holdout = conn.execute(
        """
        SELECT s.show_id, s.show_date, s.venue_id
        FROM shows s
        WHERE EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)
        ORDER BY s.show_date DESC, s.show_id DESC
        LIMIT ?
        """,
        (n_holdout_shows,),
    ).fetchall()
    holdout = list(reversed(holdout))  # chronological order for readability

    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    fold_results: list[FoldResult] = []
    all_ranks: list[int] = []

    for sh in holdout:
        cutoff = sh["show_date"]
        booster, _, n_groups = train_ranker(
            conn,
            cutoff_date=cutoff,
            negatives_per_positive=negatives_per_positive,
            freq_negatives=freq_negatives,
            uniform_negatives=uniform_negatives,
            num_iterations=num_iterations,
            half_life_years=half_life_years,
            seed=seed,
        )
        if n_groups == 0:
            # No training data before this fold — skip.
            continue

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
        for slot_idx, r in enumerate(setlist, start=1):
            positive = int(r["song_id"])
            pool = [s for s in all_song_ids if s not in played]
            rows = build_feature_rows(
                conn,
                show_date=cutoff,
                venue_id=sh["venue_id"],
                played_songs=played,
                current_set=r["set_number"],
                candidate_song_ids=pool,
                show_id=int(sh["show_id"]),
            )
            X = np.asarray([fr.to_vector() for fr in rows], dtype=np.float32)
            scores = booster.predict(X)
            order = np.argsort(-scores)
            rank = int(np.where([pool[i] == positive for i in order])[0][0]) + 1
            fold.ranks.append(rank)
            fold.slot_positions.append(slot_idx)
            all_ranks.append(rank)
            played.append(positive)
        for k in (1, 5, 20):
            fold.top_k_hits[k] = sum(1 for rk in fold.ranks if rk <= k) / max(1, len(fold.ranks))
        fold_results.append(fold)

    return _build_result(fold_results, all_ranks, seed=seed)


def _build_result(
    fold_results: list[FoldResult],
    all_ranks: list[int],
    seed: int = 0,
    n_resamples: int = 1000,
) -> WalkForwardResult:
    """Shared between walk_forward_eval and baselines.evaluate_scorer."""
    all_slot_positions: list[int] = []
    for fold in fold_results:
        all_slot_positions.extend(fold.slot_positions)

    top1_ci = bootstrap_ci(
        all_ranks, partial(topk_hit_rate, k=1), n_resamples=n_resamples, seed=seed
    )
    top5_ci = bootstrap_ci(
        all_ranks, partial(topk_hit_rate, k=5), n_resamples=n_resamples, seed=seed
    )
    top20_ci = bootstrap_ci(
        all_ranks, partial(topk_hit_rate, k=20), n_resamples=n_resamples, seed=seed
    )
    mrr_ci = bootstrap_ci(all_ranks, mrr_fn, n_resamples=n_resamples, seed=seed)
    by_slot = by_slot_position(all_ranks, all_slot_positions) if all_slot_positions else {}

    return WalkForwardResult(
        fold_results=fold_results,
        top1=topk_hit_rate(all_ranks, 1),
        top5=topk_hit_rate(all_ranks, 5),
        top20=topk_hit_rate(all_ranks, 20),
        mrr=mrr_fn(all_ranks),
        n_slots=len(all_ranks),
        top1_ci=top1_ci,
        top5_ci=top5_ci,
        top20_ci=top20_ci,
        mrr_ci=mrr_ci,
        by_slot=by_slot,
    )
