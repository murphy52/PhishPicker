"""LightGBM LambdaRank trainer.

train_ranker takes a populated DB + cutoff_date and returns a fitted booster,
the feature-column list (for the .meta.json sidecar), and the number of
training groups. Sample weights optionally apply a 7-year exponential decay
(half-life) to de-emphasize pre-hiatus setlists.
"""

import sqlite3
from datetime import date

import lightgbm as lgb
import numpy as np

from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.build import build_feature_rows
from phishpicker.train.dataset import iter_training_groups
from phishpicker.train.features import FEATURE_COLUMNS


def train_ranker(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    seed: int = 0,
    num_iterations: int = 300,
    learning_rate: float = 0.05,
    num_leaves: int = 63,
    half_life_years: float | None = 7.0,
) -> tuple[lgb.Booster, list[str], int]:
    bigram_cache = compute_bigram_probs(conn, cutoff_date=cutoff_date)
    all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))

    X_rows: list[list[float]] = []
    y: list[int] = []
    group_sizes: list[int] = []
    row_weights: list[float] = []

    for tg in iter_training_groups(
        conn,
        cutoff_date=cutoff_date,
        negatives_per_positive=negatives_per_positive,
        freq_negatives=freq_negatives,
        uniform_negatives=uniform_negatives,
        seed=seed,
    ):
        candidate_ids = [tg.positive_song_id, *tg.negative_song_ids]
        rows = build_feature_rows(
            conn,
            show_date=tg.show_date,
            venue_id=tg.venue_id,
            played_songs=list(tg.played_before_slot),
            current_set=tg.current_set,
            candidate_song_ids=candidate_ids,
            show_id=tg.show_id,
            bigram_cache=bigram_cache,
            all_show_dates=all_show_dates,
        )
        w = _recency_weight(tg.show_date, cutoff_date, half_life_years)
        for r in rows:
            X_rows.append(r.to_vector())
            y.append(1 if r.song_id == tg.positive_song_id else 0)
            row_weights.append(w)
        group_sizes.append(len(candidate_ids))

    if not X_rows:
        raise ValueError("No training data — cutoff_date excludes all shows?")

    X = np.asarray(X_rows, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.int32)
    group_arr = np.asarray(group_sizes, dtype=np.int32)
    w_arr = np.asarray(row_weights, dtype=np.float32)

    model = lgb.LGBMRanker(
        objective="lambdarank",
        n_estimators=num_iterations,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        random_state=seed,
        verbose=-1,
    )
    model.fit(X, y_arr, group=group_arr, sample_weight=w_arr)
    return model.booster_, list(FEATURE_COLUMNS), len(group_sizes)


def _recency_weight(show_date: str, cutoff_date: str, half_life_years: float | None) -> float:
    if half_life_years is None:
        return 1.0
    days = (date.fromisoformat(cutoff_date) - date.fromisoformat(show_date)).days
    years = max(0.0, days / 365.25)
    return 0.5 ** (years / half_life_years)
