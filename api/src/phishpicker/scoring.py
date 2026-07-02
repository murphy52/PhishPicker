"""Pure scoring engine for the prediction game.

Everything here is a function of plain dicts/lists — no DB, no model. Inputs
are the frozen pre-show bracket, the normalized actual setlist, and the
captured live next-song calls (see docs/plans/2026-07-01-scoring-game-design.md).
"""

# 'S' (soundcheck) intentionally absent — never predicted, never scored.
_SET_ORDER = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}

# Point ladder — values are tunable; the ordering does the work.
PTS_SOMEWHERE, PTS_RIGHT_SET, PTS_EXACT, PTS_OPENER = 5, 15, 40, 60
PTS_NEXT_SONG = 30
COMBO = {1: 1.0, 2: 1.5}  # 3rd+ in a row -> 2.0 (cap)
COMBO_CAP = 2.0
# E2/E3 openers are NOT bonus-eligible (they score plain exact).
OPENER_SLOTS = {("1", 1), ("2", 1), ("3", 1), ("4", 1), ("E", 1)}

# Classification tiers, weakest -> strongest.
_TIER_BASE = {"somewhere": PTS_SOMEWHERE, "right_set": PTS_RIGHT_SET, "exact": PTS_EXACT}
_TIER_RANK = {"absent": 0, "somewhere": 1, "right_set": 2, "exact": 3}


def _classify_occurrence(pick: dict, row: dict) -> str:
    if row["song_id"] != pick["song_id"]:
        return "absent"
    if row["set_number"] == pick["set_number"]:
        if row["position"] == pick["position"]:
            return "exact"
        return "right_set"
    return "somewhere"


def classify_foresight(pick: dict, actual: list[dict]) -> tuple[str, int]:
    """Best placement tier for one bracket pick against the actual setlist:
    exact > right_set > somewhere > absent. Opener bonus and consume-once
    bookkeeping live in score_foresight."""
    best = "absent"
    for row in actual:
        tier = _classify_occurrence(pick, row)
        if _TIER_RANK[tier] > _TIER_RANK[best]:
            best = tier
    return best, _TIER_BASE.get(best, 0)


def score_foresight(
    bracket: list[dict], actual: list[dict]
) -> tuple[dict[int, dict], list[dict]]:
    """Whole-bracket Foresight pass.

    Returns (claims_by_actual_index, pick_outcomes):
    - claims_by_actual_index: actual index -> {"base", "reason", "pick"};
      each actual occurrence is claimed by at most one pick (consume-once),
      and an exact hit on an OPENER_SLOTS slot upgrades to PTS_OPENER.
    - pick_outcomes: one entry per bracket pick, including absent whiffs —
      the recap's "which picks missed" list.
    """
    claims: dict[int, dict] = {}
    outcomes: list[dict] = []
    consumed: set[int] = set()
    for pick in bracket:
        # Best unconsumed occurrence of this pick's song.
        best_tier, best_idx = "absent", None
        for idx, row in enumerate(actual):
            if idx in consumed:
                continue
            tier = _classify_occurrence(pick, row)
            if _TIER_RANK[tier] > _TIER_RANK[best_tier]:
                best_tier, best_idx = tier, idx
        if best_idx is None:
            outcomes.append(
                {"pick": pick, "reason": "absent", "base": 0, "actual_index": None}
            )
            continue
        reason, base = best_tier, _TIER_BASE[best_tier]
        if reason == "exact" and (pick["set_number"], pick["position"]) in OPENER_SLOTS:
            reason, base = "opener", PTS_OPENER
        consumed.add(best_idx)
        claims[best_idx] = {"base": base, "reason": reason, "pick": pick}
        outcomes.append(
            {"pick": pick, "reason": reason, "base": base, "actual_index": best_idx}
        )
    return claims, outcomes


def normalize_setlist(rows: list[dict]) -> list[dict]:
    """Raw live_songs/setlist rows -> the scored setlist: soundcheck dropped,
    ordered by set then position-within-set."""
    kept = [r for r in rows if r["set_number"] in _SET_ORDER]
    return sorted(kept, key=lambda r: (_SET_ORDER[r["set_number"]], r["position"]))
