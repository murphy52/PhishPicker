"""Runtime scorer protocol + the two concrete implementations.

Two scorers share a common interface so `/predict` doesn't have to know which
is active. The API's lifespan picks LightGBM if `model.lgb` exists and its
feature-column schema matches FEATURE_COLUMNS; otherwise it falls back to
the heuristic — the walking-skeleton code path.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from phishpicker.model.heuristic import Context
from phishpicker.model.heuristic import score as heuristic_score
from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.model.stats import compute_song_stats
from phishpicker.train.build import build_feature_rows
from phishpicker.train.features import FEATURE_COLUMNS


class Scorer(Protocol):
    name: str

    def score_candidates(
        self,
        conn: sqlite3.Connection,
        show_date: str,
        venue_id: int | None,
        played_songs: list[int],
        current_set: str,
        candidate_song_ids: list[int],
        prev_trans_mark: str = ",",
        prev_set_number: str | None = None,
        slots_into_current_set: int = 1,
        stats_cache: dict | None = None,
        ext_cache: dict | None = None,
        bigram_cache: dict | None = None,
    ) -> list[tuple[int, float]]: ...


@dataclass
class HeuristicScorer:
    name: str = "heuristic"

    def score_candidates(
        self,
        conn: sqlite3.Connection,
        show_date: str,
        venue_id: int | None,
        played_songs: list[int],
        current_set: str,
        candidate_song_ids: list[int],
        prev_trans_mark: str = ",",
        prev_set_number: str | None = None,
        slots_into_current_set: int = 1,
        stats_cache: dict | None = None,
        ext_cache: dict | None = None,
        bigram_cache: dict | None = None,
    ) -> list[tuple[int, float]]:
        # Heuristic only uses song_stats; ext_cache / bigram_cache kept for
        # Protocol compatibility.
        del prev_trans_mark, prev_set_number, slots_into_current_set
        del ext_cache, bigram_cache
        stats = (
            stats_cache
            if stats_cache is not None
            else compute_song_stats(conn, show_date, venue_id, candidate_song_ids)
        )
        ctx = Context(current_set=current_set, current_position=len(played_songs) + 1)
        return [(sid, heuristic_score(stats[sid], ctx)) for sid in candidate_song_ids]


@dataclass
class LightGBMRuntimeScorer:
    scorer: LightGBMScorer
    name: str = "lightgbm"

    def score_candidates(
        self,
        conn: sqlite3.Connection,
        show_date: str,
        venue_id: int | None,
        played_songs: list[int],
        current_set: str,
        candidate_song_ids: list[int],
        prev_trans_mark: str = ",",
        prev_set_number: str | None = None,
        slots_into_current_set: int = 1,
        stats_cache: dict | None = None,
        ext_cache: dict | None = None,
        bigram_cache: dict | None = None,
    ) -> list[tuple[int, float]]:
        if not candidate_song_ids:
            return []
        rows = build_feature_rows(
            conn,
            show_date=show_date,
            venue_id=venue_id,
            played_songs=played_songs,
            current_set=current_set,
            candidate_song_ids=candidate_song_ids,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
            slots_into_current_set=slots_into_current_set,
            stats_cache=stats_cache,
            ext_cache=ext_cache,
            bigram_cache=bigram_cache,
        )
        X = np.asarray([r.to_vector() for r in rows], dtype=np.float32)
        scores = self.scorer.score(X)
        return list(zip(candidate_song_ids, scores.tolist(), strict=True))


def load_runtime_scorer(model_path: Path) -> Scorer:
    """Load the LightGBM scorer from `model_path`. Falls back to the heuristic
    on any of: missing file, unreadable model, feature-schema mismatch.

    Returns a ready-to-use Scorer. The caller is expected to log which one is
    active; this function just picks the best available.
    """
    try:
        if not Path(model_path).exists():
            return HeuristicScorer()
        loaded = LightGBMScorer.load(model_path)
        loaded.assert_compatible_with(FEATURE_COLUMNS)
        return LightGBMRuntimeScorer(scorer=loaded)
    except Exception:
        return HeuristicScorer()
