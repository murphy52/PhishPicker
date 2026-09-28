"""Walk-forward evaluation.

For each of the last N shows (reverse-chron), refit a LightGBM ranker on all
prior-show setlists, then score every slot of the held-out show. Metrics are
aggregated across all held-out slots.

Per carry-forward §4 (feature leakage): features that depend on tour/run state
(tour_position, times_this_tour, etc.) are recomputed from-scratch per fold.
That happens naturally here because build_feature_rows is called with
`show_date = heldout_show_date` and reads fresh DB rows.
"""

import logging
import sqlite3
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from functools import partial

import lightgbm as lgb
import numpy as np

from phishpicker.train.build import build_feature_rows
from phishpicker.train.exclusions import EXCLUDED_SHOW_IDS
from phishpicker.train.metrics import (
    bootstrap_ci,
    by_slot_position,
    topk_hit_rate,
)
from phishpicker.train.metrics import (
    mrr as mrr_fn,
)
from phishpicker.train.trainer import train_ranker

log = logging.getLogger(__name__)


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
    holdout = select_holdout_shows(conn, n_holdout_shows)
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    # Precompute sorted show_dates once per walk-forward run — compute_song_stats
    # uses this for O(log N) shows_between lookups instead of SQL-per-song.
    all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))

    fold_results: list[FoldResult] = []
    all_ranks: list[int] = []

    for fold_idx, sh in enumerate(holdout, start=1):
        cutoff = sh["show_date"]
        fold_t0 = time.monotonic()
        log.info(
            "fold %d/%d: training up to %s (show_id=%d)",
            fold_idx,
            len(holdout),
            cutoff,
            sh["show_id"],
        )
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

        fold = _rank_show(conn, booster.predict, sh, all_song_ids, all_show_dates)
        all_ranks.extend(fold.ranks)
        fold_results.append(fold)
        log.info(
            "fold %d/%d done in %.1fs: %d slots, Top-1=%.3f Top-5=%.3f",
            fold_idx,
            len(holdout),
            time.monotonic() - fold_t0,
            len(fold.ranks),
            fold.top_k_hits.get(1, 0.0),
            fold.top_k_hits.get(5, 0.0),
        )

    return _build_result(fold_results, all_ranks, seed=seed)


def select_holdout_shows(
    conn: sqlite3.Connection,
    n_holdout_shows: int,
    excluded_show_ids: Collection[int] = EXCLUDED_SHOW_IDS,
) -> list[sqlite3.Row]:
    """The last `n_holdout_shows` shows, oldest first. Walk-forward, the
    baselines and evaluate_booster all grade on exactly this set.

    Skips shows with no setlist rows (phish.net lists future-dated placeholders)
    and `excluded_show_ids` (see train.exclusions), reaching further back so
    the holdout stays full.
    """
    rows = conn.execute(
        """
        SELECT s.show_id, s.show_date, s.venue_id
        FROM shows s
        WHERE EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)
        ORDER BY s.show_date DESC, s.show_id DESC
        """
    ).fetchall()
    kept = [r for r in rows if r["show_id"] not in excluded_show_ids][:n_holdout_shows]
    return list(reversed(kept))


def evaluate_booster(
    conn: sqlite3.Connection,
    booster: lgb.Booster,
    n_holdout_shows: int = 20,
) -> WalkForwardResult:
    """Score one fixed model on the walk-forward holdout, with no refitting.

    Use it to grade the model already in prod on the same shows a new
    training run is graded on. Metrics from two different holdouts can't be
    compared.
    """
    holdout = select_holdout_shows(conn, n_holdout_shows)
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))
    fold_results: list[FoldResult] = []
    all_ranks: list[int] = []
    for sh in holdout:
        fold = _rank_show(conn, booster.predict, sh, all_song_ids, all_show_dates)
        all_ranks.extend(fold.ranks)
        fold_results.append(fold)
    return _build_result(fold_results, all_ranks)


def _rank_show(
    conn: sqlite3.Connection,
    predict: Callable[[np.ndarray], np.ndarray],
    sh: sqlite3.Row,
    all_song_ids: list[int],
    all_show_dates: list[str],
) -> FoldResult:
    """Rank the actual song at every slot of one held-out show."""
    cutoff = sh["show_date"]
    setlist = conn.execute(
        "SELECT set_number, position, song_id, trans_mark FROM setlist_songs "
        "WHERE show_id = ? ORDER BY set_number, position",
        (sh["show_id"],),
    ).fetchall()

    played: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None
    slots_into_current_set = 1
    fold = FoldResult(
        heldout_show_id=int(sh["show_id"]),
        heldout_show_date=cutoff,
        train_cutoff_date=cutoff,
    )
    for slot_idx, r in enumerate(setlist, start=1):
        positive = int(r["song_id"])
        if prev_set_number is not None and prev_set_number != r["set_number"]:
            slots_into_current_set = 1
        # Rank the positive against ALL songs, not just not-yet-played.
        # Two reasons: (1) shows legitimately repeat songs (reprises), so
        # the positive may already be in `played`; (2) production applies
        # hard-rules post-processing separately — eval should measure the
        # raw model signal including how well `played_already_this_run`
        # features suppress repeats.
        pool = list(all_song_ids)
        rows = build_feature_rows(
            conn,
            show_date=cutoff,
            venue_id=sh["venue_id"],
            played_songs=played,
            current_set=r["set_number"],
            candidate_song_ids=pool,
            show_id=int(sh["show_id"]),
            all_show_dates=all_show_dates,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
            slots_into_current_set=slots_into_current_set,
        )
        X = np.asarray([fr.to_vector() for fr in rows], dtype=np.float32)
        scores = predict(X)
        order = np.argsort(-scores)
        rank = int(np.where([pool[i] == positive for i in order])[0][0]) + 1
        fold.ranks.append(rank)
        fold.slot_positions.append(slot_idx)
        played.append(positive)
        prev_trans_mark = r["trans_mark"] or ","
        prev_set_number = r["set_number"]
        slots_into_current_set += 1
    for k in (1, 5, 20):
        fold.top_k_hits[k] = sum(1 for rk in fold.ranks if rk <= k) / max(1, len(fold.ranks))
    return fold


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
