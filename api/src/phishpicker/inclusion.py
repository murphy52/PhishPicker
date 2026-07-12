"""Serving for the show-level inclusion model — the "Likely Tonight" list.

Given an upcoming show, returns songs ranked by P(appears anywhere tonight).
Independent of the slot-level next-song ranker; loaded from its own artifact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    InclusionHistory,
)


def load_inclusion_scorer(path: Path) -> LightGBMScorer:
    scorer = LightGBMScorer.load(path)
    scorer.assert_compatible_with(INCLUSION_FEATURE_COLUMNS)
    return scorer


def likely_tonight(
    read_conn: sqlite3.Connection,
    show_id: int,
    scorer: LightGBMScorer,
    top_n: int = 30,
) -> list[dict]:
    """Ranked inclusion predictions for `show_id` (must exist in `shows`)."""
    hist = InclusionHistory(read_conn)
    try:
        ctx = hist.context_for(show_id)
    except KeyError:
        return []

    sids = hist.candidate_ids(ctx.show_date)
    X, kept = hist.feature_matrix(ctx, sids)
    if not kept:
        return []

    probs = scorer.score(X)
    order = sorted(range(len(kept)), key=lambda i: -probs[i])[:top_n]

    top_ids = [kept[i] for i in order]
    names = dict(
        read_conn.execute(
            f"SELECT song_id, name FROM songs WHERE song_id IN "
            f"({','.join('?' * len(top_ids))})",
            top_ids,
        ).fetchall()
    )
    return [
        {
            "song_id": kept[i],
            "name": names.get(kept[i], str(kept[i])),
            "probability": round(float(probs[i]), 4),
        }
        for i in order
    ]
