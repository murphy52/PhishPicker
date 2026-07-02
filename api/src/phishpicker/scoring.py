"""Pure scoring engine for the prediction game.

Everything here is a function of plain dicts/lists — no DB, no model. Inputs
are the frozen pre-show bracket, the normalized actual setlist, and the
captured live next-song calls (see docs/plans/2026-07-01-scoring-game-design.md).
"""

# 'S' (soundcheck) intentionally absent — never predicted, never scored.
_SET_ORDER = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}


def normalize_setlist(rows: list[dict]) -> list[dict]:
    """Raw live_songs/setlist rows -> the scored setlist: soundcheck dropped,
    ordered by set then position-within-set."""
    kept = [r for r in rows if r["set_number"] in _SET_ORDER]
    return sorted(kept, key=lambda r: (_SET_ORDER[r["set_number"]], r["position"]))
