"""Song→song transition probabilities used as a LightGBM feature.

Bigrams are strictly within-set, within-show. They respect a cutoff_date so
walk-forward evaluation folds don't leak future setlists into training.
"""

import sqlite3
from collections import defaultdict


def compute_bigram_probs(
    conn: sqlite3.Connection,
    cutoff_date: str,
    alpha: float = 1.0,
    candidate_count: int = 950,
) -> dict[tuple[int, int], float]:
    """Return {(prev_song_id, next_song_id): P(next | prev)} using setlists
    strictly before cutoff_date. Transitions do not cross set or show boundaries.

    Laplace-smoothed: prob = (count + alpha) / (row_total + alpha * V)
    where V is the candidate song count (rough vocabulary size). alpha=0 gives
    the raw empirical conditional.
    """
    rows = conn.execute(
        """
        SELECT ss.show_id, ss.set_number, ss.position, ss.song_id
        FROM setlist_songs ss JOIN shows s USING (show_id)
        WHERE s.show_date < ?
        ORDER BY ss.show_id, ss.set_number, ss.position
        """,
        (cutoff_date,),
    ).fetchall()

    counts: dict[tuple[int, int], int] = defaultdict(int)
    row_totals: dict[int, int] = defaultdict(int)
    prev_song: int | None = None
    prev_key: tuple[int, str] | None = None
    for r in rows:
        key = (r["show_id"], r["set_number"])
        if prev_song is not None and prev_key == key:
            counts[(prev_song, r["song_id"])] += 1
            row_totals[prev_song] += 1
        prev_song = r["song_id"]
        prev_key = key

    out: dict[tuple[int, int], float] = {}
    if alpha == 0.0:
        for (p, n), c in counts.items():
            out[(p, n)] = c / row_totals[p]
        return out

    for (p, n), c in counts.items():
        denom = row_totals[p] + alpha * candidate_count
        out[(p, n)] = (c + alpha) / denom
    return out
