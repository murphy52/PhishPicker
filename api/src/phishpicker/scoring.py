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


def score_live(actual: list[dict], next_call_by_index: dict) -> dict[int, dict]:
    """Live ledger base claims: actual index i (i>=1) whose song matches the
    captured next-song call that was live when it revealed. Index 0 (the
    opener) is never a live event — live calling starts after the opener."""
    claims: dict[int, dict] = {}
    for i in range(1, len(actual)):
        if next_call_by_index.get(i) == actual[i]["song_id"]:
            claims[i] = {"base": PTS_NEXT_SONG}
    return claims


def resolve_claims(
    foresight: dict[int, dict], live: dict[int, dict], actual: list[dict]
) -> list[dict]:
    """Best-claim-wins: each actual song banks the larger BASE of its two
    ledger claims, once. Ties go to Foresight (the premium tier). The losing
    claim is recorded so the UI can show what was beaten."""
    attributions: list[dict] = []
    for i, row in enumerate(actual):
        f, lv = foresight.get(i), live.get(i)
        att = {
            "index": i,
            "song_id": row["song_id"],
            "set_number": row["set_number"],
            "position": row["position"],
            "ledger": None,
            "base": 0,
            "reason": None,
            "beaten_claim": None,
        }
        if f is not None and (lv is None or f["base"] >= lv["base"]):
            att.update(ledger="foresight", base=f["base"], reason=f["reason"])
            if lv is not None:
                att["beaten_claim"] = {
                    "ledger": "live",
                    "reason": "next_song",
                    "base": lv["base"],
                }
        elif lv is not None:
            att.update(ledger="live", base=lv["base"], reason="next_song")
            if f is not None:
                att["beaten_claim"] = {
                    "ledger": "foresight",
                    "reason": f["reason"],
                    "base": f["base"],
                }
        attributions.append(att)
    return attributions


def apply_combo(
    actual: list[dict], attributions: list[dict], next_call_by_index: dict
) -> list[dict]:
    """Streak/combo pass, decoupled from the ledger.

    - The streak counts consecutive correct #1 next-song calls, whichever
      ledger banks the song. A wrong call resets it to 0.
    - No captured call (key absent/None) is a NO-EVENT: the streak neither
      advances nor resets — sync gaps and sha-mismatch skips must not punish
      the combo. Index 0 (the opener) is always a no-event.
    - The multiplier pays only on Live-banked points; Foresight-banked songs
      advance the streak but keep final == base.
    """
    streak = 0
    out: list[dict] = []
    for att in attributions:
        i = att["index"]
        call = next_call_by_index.get(i) if i > 0 else None
        if call is None:
            called_right = None
        else:
            called_right = call == actual[i]["song_id"]
            streak = streak + 1 if called_right else 0
        if att["ledger"] == "live":
            mult = COMBO.get(streak, COMBO_CAP)
            final = att["base"] * mult
        else:
            mult = None
            final = att["base"]
        out.append(
            {**att, "called_right": called_right, "streak": streak, "mult": mult, "final": final}
        )
    return out


def normalize_setlist(rows: list[dict]) -> list[dict]:
    """Raw live_songs/setlist rows -> the scored setlist: soundcheck dropped,
    ordered by set then position-within-set."""
    kept = [r for r in rows if r["set_number"] in _SET_ORDER]
    return sorted(kept, key=lambda r: (_SET_ORDER[r["set_number"]], r["position"]))
