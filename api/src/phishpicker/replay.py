"""Side-by-side replay of two LightGBM model artifacts on a historical show.

For every slot of a real setlist, re-score the same candidate pool with both
models and compare where each one ranks the actual-next-song. Useful for
qualitatively inspecting what changed between model versions — we want a number
like "model B moved Sigma Oasis from rank 12 to rank 4" rather than just a
delta in aggregate MRR.

Pure-python: the CLI wrapper in `phishpicker.cli` handles formatting.
"""

import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.build import build_feature_rows
from phishpicker.train.features import FEATURE_COLUMNS


class ReplayError(ValueError):
    """Raised when replay can't run — bad show_id, schema mismatch, etc.

    Subclasses ValueError so test_replay_rejects_schema_mismatch can match on
    either; also gives callers a single exception type to catch at the CLI.
    """


def replay_show(
    conn: sqlite3.Connection,
    *,
    model_a_path: Path,
    model_b_path: Path,
    show_id: int,
    top_k: int = 10,
    diff_threshold: int = 5,
) -> dict[str, Any]:
    """Re-score every slot of `show_id` with both models; return a structured
    result dict keyed ``{"show": ..., "slots": [...], "summary": {...}}``.

    Each slot dict contains:
    - slot: 1-indexed slot number
    - set: set_number string ("1", "2", "E", ...)
    - actual_song_id / actual_song_name
    - rank_a, rank_b: 1-indexed rank of the actual-next-song
    - delta: rank_b - rank_a (negative = B beat A)
    - top_a, top_b: list of top_k (song_id, song_name) tuples
    """
    scorer_a = _load_and_verify(model_a_path)
    scorer_b = _load_and_verify(model_b_path)

    show = conn.execute(
        "SELECT show_id, show_date, venue_id FROM shows WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if show is None:
        raise ReplayError(f"Unknown show_id={show_id}")

    setlist = conn.execute(
        "SELECT set_number, position, song_id, trans_mark FROM setlist_songs "
        "WHERE show_id = ? ORDER BY set_number, position",
        (show_id,),
    ).fetchall()
    if not setlist:
        raise ReplayError(f"show_id={show_id} has no setlist rows")

    venue_name = None
    if show["venue_id"] is not None:
        v = conn.execute(
            "SELECT name FROM venues WHERE venue_id = ?", (show["venue_id"],)
        ).fetchone()
        if v:
            venue_name = v["name"]

    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    song_names = {r["song_id"]: r["name"] for r in conn.execute("SELECT song_id, name FROM songs")}
    all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))

    slots: list[dict[str, Any]] = []
    played: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None
    for slot_idx, row in enumerate(setlist, start=1):
        positive = int(row["song_id"])
        feature_rows = build_feature_rows(
            conn,
            show_date=show["show_date"],
            venue_id=show["venue_id"],
            played_songs=played,
            current_set=row["set_number"],
            candidate_song_ids=all_song_ids,
            show_id=show_id,
            all_show_dates=all_show_dates,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
        )
        X = np.asarray([fr.to_vector() for fr in feature_rows], dtype=np.float32)

        rank_a, top_a = _rank_and_top(scorer_a.score(X), all_song_ids, song_names, positive, top_k)
        rank_b, top_b = _rank_and_top(scorer_b.score(X), all_song_ids, song_names, positive, top_k)

        slots.append(
            {
                "slot": slot_idx,
                "set": row["set_number"],
                "actual_song_id": positive,
                "actual_song_name": song_names.get(positive, f"#{positive}"),
                "rank_a": rank_a,
                "rank_b": rank_b,
                "delta": rank_b - rank_a,
                "top_a": top_a,
                "top_b": top_b,
            }
        )
        played.append(positive)
        prev_trans_mark = row["trans_mark"] or ","
        prev_set_number = row["set_number"]

    return {
        "show": {
            "show_id": int(show["show_id"]),
            "show_date": show["show_date"],
            "venue_id": show["venue_id"],
            "venue_name": venue_name,
        },
        "model_a_path": str(model_a_path),
        "model_b_path": str(model_b_path),
        "top_k": top_k,
        "diff_threshold": diff_threshold,
        "slots": slots,
        "summary": _summarize(slots, diff_threshold),
    }


def _load_and_verify(path: Path) -> LightGBMScorer:
    """Load a LightGBMScorer and assert its feature_columns match FEATURE_COLUMNS.

    Wraps the ValueError in a ReplayError so CLI callers can handle one type.
    """
    try:
        scorer = LightGBMScorer.load(Path(path))
    except FileNotFoundError as exc:
        raise ReplayError(f"Model file not found: {path}") from exc
    try:
        scorer.assert_compatible_with(FEATURE_COLUMNS)
    except ValueError as exc:
        raise ReplayError(f"Model {path} has schema mismatch: {exc}") from exc
    return scorer


def _rank_and_top(
    scores: np.ndarray,
    candidate_ids: list[int],
    song_names: dict[int, str],
    positive_id: int,
    top_k: int,
) -> tuple[int, list[tuple[int, str]]]:
    order = np.argsort(-scores)
    # Rank of positive (1-indexed). np.where returns the first match index.
    ordered_ids = [candidate_ids[i] for i in order]
    rank = ordered_ids.index(positive_id) + 1
    top = [
        (candidate_ids[i], song_names.get(candidate_ids[i], f"#{candidate_ids[i]}"))
        for i in order[:top_k]
    ]
    return rank, top


def _summarize(slots: list[dict[str, Any]], diff_threshold: int) -> dict[str, float]:
    ranks_a = [s["rank_a"] for s in slots]
    ranks_b = [s["rank_b"] for s in slots]
    n = max(1, len(slots))
    mean_rank_a = sum(ranks_a) / n
    mean_rank_b = sum(ranks_b) / n
    mrr_a = sum(1.0 / r for r in ranks_a) / n if ranks_a else 0.0
    mrr_b = sum(1.0 / r for r in ranks_b) / n if ranks_b else 0.0
    # delta = rank_b - rank_a.  Negative delta => B ranked the actual-next-song
    # higher than A did => B beat A.
    b_beats_a = sum(1 for s in slots if -s["delta"] >= diff_threshold)
    a_beats_b = sum(1 for s in slots if s["delta"] >= diff_threshold)
    return {
        "n_slots": len(slots),
        "mean_rank_a": mean_rank_a,
        "mean_rank_b": mean_rank_b,
        "mrr_a": mrr_a,
        "mrr_b": mrr_b,
        "b_beats_a_count": b_beats_a,
        "a_beats_b_count": a_beats_b,
        "diff_threshold": diff_threshold,
    }
