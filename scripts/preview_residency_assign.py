"""Assignment-based residency forecaster for Sphere Nights 4-9.

Instead of greedy slot-by-slot picking (which front-loads the A-list
and starves the back end), solve the full 6×18 residency as a single
optimization problem:

    maximize  Σ_{(song, slot) ∈ assignment}  score(song, slot)
    subject to  each song used at most once across the 108 slots
                each slot filled by exactly one song

With `--pace` we upgrade the LAP to an MILP by adding a per-night cap
on how many top-12mo-favorites can land on any one night, so the
A-list is spread across the residency rather than clustered wherever
the scorer's log-odds peak.

Songs are scored per slot with played_songs=[] (no within-residency
dedup in the scorer), so the late-night candidate pool isn't drained
by the simulator's own prior picks.

Run from the api/ directory:
    ~/.local/bin/uv run python ../scripts/preview_residency_assign.py
    ~/.local/bin/uv run python ../scripts/preview_residency_assign.py --pace
"""

import argparse
import json
import shutil
import sqlite3
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linear_sum_assignment, milp
from scipy.sparse import csr_matrix

from phishpicker.model.scorer import load_runtime_scorer
from phishpicker.model.stats import compute_song_stats
from phishpicker.train.bigrams import compute_bigram_probs
from phishpicker.train.extended_stats import compute_extended_stats

SIM_DB_PATH = Path("/tmp/sim_residency_assign.db")
REAL_DB_PATH = Path("data/phishpicker.db")
MODEL_PATH = Path("data/model.lgb")
PREVIEW_DIR = Path("data/previews")

NIGHTS = [
    ("Night 4", "2026-04-23", 1764702416),
    ("Night 5", "2026-04-24", 1764702441),
    ("Night 6", "2026-04-25", 1764702466),
    ("Night 7", "2026-04-30", 1764702491),
    ("Night 8", "2026-05-01", 1764702513),
    ("Night 9", "2026-05-02", 1764702539),
]
VENUE_ID = 1597
STRUCTURE = [("1", 9), ("2", 7), ("E", 2)]
PRIOR_RESIDENCY_SHOW_IDS = (1764702178, 1764702334, 1764702381)

NEG_INF = -1e9


def solve_paced_milp(
    reward: np.ndarray,
    *,
    premium_song_indices: list[int],
    night_slot_indices: list[list[int]],
    night_cap: int,
    total_premiums_target: int,
    top_per_slot: int = 40,
) -> tuple[np.ndarray, np.ndarray]:
    """MILP: LAP with an extra per-night cap on top-25 favorites.

    Shrinks the candidate pool to the top-`top_per_slot` songs per slot
    (union'd and premium-set forced in) so HiGHS can solve a ~(300×108)
    binary program interactively. Returns (row_ind, col_ind) in the same
    shape as linear_sum_assignment for drop-in compatibility.
    """
    k, s = reward.shape
    # Reduce: keep each slot's top candidates, plus all premiums.
    kept: set[int] = set()
    for j in range(s):
        top_idx = np.argpartition(-reward[:, j], min(top_per_slot, k - 1))[:top_per_slot]
        kept.update(int(i) for i in top_idx)
    kept.update(premium_song_indices)
    # Feasibility floor: need at least `s` distinct songs to fill all slots
    # under the one-song-per-residency constraint.
    if len(kept) < s:
        # Backfill with songs having highest max-reward.
        song_max = reward.max(axis=1)
        backfill_order = np.argsort(-song_max)
        for idx in backfill_order:
            if len(kept) >= s + 20:  # small headroom
                break
            kept.add(int(idx))
    kept_indices = sorted(kept)
    local_of = {orig: local for local, orig in enumerate(kept_indices)}
    kept_reward = reward[kept_indices]
    kk, ss = kept_reward.shape  # ss == s
    print(f"[pace] MILP pool: {kk} songs × {ss} slots = {kk * ss} binaries")

    local_premiums = [local_of[i] for i in premium_song_indices if i in local_of]

    # x[i*ss + j] = 1 iff local song i assigned to slot j. We minimize,
    # so negate rewards.
    c = -kept_reward.flatten()

    # Slot constraint: each slot exactly 1 song (rows = slots).
    row_slot, col_slot = [], []
    for j in range(ss):
        for i in range(kk):
            row_slot.append(j)
            col_slot.append(i * ss + j)
    slot_A = csr_matrix((np.ones(len(row_slot)), (row_slot, col_slot)), shape=(ss, kk * ss))

    # Song constraint: each song ≤ 1.
    row_song, col_song = [], []
    for i in range(kk):
        for j in range(ss):
            row_song.append(i)
            col_song.append(i * ss + j)
    song_A = csr_matrix((np.ones(len(row_song)), (row_song, col_song)), shape=(kk, kk * ss))

    # Per-night premium cap.
    row_cap, col_cap = [], []
    for n, slot_js in enumerate(night_slot_indices):
        for i in local_premiums:
            for j in slot_js:
                row_cap.append(n)
                col_cap.append(i * ss + j)
    cap_A = csr_matrix(
        (np.ones(len(row_cap)), (row_cap, col_cap)),
        shape=(len(night_slot_indices), kk * ss),
    )

    # Total premiums placed == target (spread the full set across residency).
    total_row = np.zeros(kk * ss)
    for i in local_premiums:
        for j in range(ss):
            total_row[i * ss + j] = 1
    total_A = csr_matrix(total_row.reshape(1, -1))

    constraints = [
        LinearConstraint(slot_A, lb=1, ub=1),
        LinearConstraint(song_A, lb=0, ub=1),
        LinearConstraint(cap_A, lb=0, ub=night_cap),
        LinearConstraint(total_A, lb=total_premiums_target, ub=total_premiums_target),
    ]
    res = milp(
        c,
        constraints=constraints,
        integrality=np.ones(kk * ss),
        bounds=Bounds(lb=0, ub=1),
    )
    if not res.success:
        raise RuntimeError(f"MILP failed: {res.message}")

    x = np.asarray(res.x).reshape(kk, ss)
    # For each slot column, find the local song index that equals 1.
    chosen_local = np.argmax(x, axis=0)
    row_ind = np.array([kept_indices[i] for i in chosen_local], dtype=np.int64)
    col_ind = np.arange(ss, dtype=np.int64)
    return row_ind, col_ind


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--pace",
        action="store_true",
        help="MILP instead of LAP: add per-night cap on top-25 favorites "
        "to spread the A-list across the residency",
    )
    ap.add_argument(
        "--night-cap",
        type=int,
        default=2,
        help="max top-25 premiums allowed on any one night (default 2)",
    )
    args = ap.parse_args()

    if SIM_DB_PATH.exists():
        SIM_DB_PATH.unlink()
    shutil.copy(REAL_DB_PATH, SIM_DB_PATH)

    sim_conn = sqlite3.connect(SIM_DB_PATH)
    sim_conn.row_factory = sqlite3.Row

    already_played_ids = {
        r[0]
        for r in sim_conn.execute(
            f"SELECT DISTINCT song_id FROM setlist_songs WHERE show_id IN "
            f"({','.join('?' * len(PRIOR_RESIDENCY_SHOW_IDS))})",
            PRIOR_RESIDENCY_SHOW_IDS,
        ).fetchall()
    }

    all_song_ids = [
        r[0] for r in sim_conn.execute("SELECT song_id FROM songs").fetchall()
    ]
    eligible = [sid for sid in all_song_ids if sid not in already_played_ids]
    k = len(eligible)
    song_idx_by_id = {sid: i for i, sid in enumerate(eligible)}
    song_names = dict(
        sim_conn.execute("SELECT song_id, name FROM songs").fetchall()
    )

    latest_cutoff = sim_conn.execute(
        "SELECT MAX(show_date) FROM shows WHERE show_date <= '2026-04-19'"
    ).fetchone()[0]
    twelve_mo_ago = "2025-04-19"
    top_12mo_rows = list(
        sim_conn.execute(
            """
            SELECT s.song_id, s.name, COUNT(*) AS n
            FROM setlist_songs ss
            JOIN shows sh USING (show_id)
            JOIN songs s USING (song_id)
            WHERE sh.show_date BETWEEN ? AND ?
            GROUP BY s.song_id
            ORDER BY n DESC
            LIMIT 25
            """,
            (twelve_mo_ago, latest_cutoff),
        )
    )

    print(f"Eligible candidate songs: {k}")
    print(f"N1-3 already-played (excluded): {len(already_played_ids)}")

    # Build slot list with prev_set context (the set_number of the slot
    # immediately before this one in the same show's play order).
    slots: list[dict] = []
    for night_idx, (label, show_date, show_id) in enumerate(NIGHTS):
        prev_set: str | None = None
        for set_num, n_slots in STRUCTURE:
            for pos in range(1, n_slots + 1):
                slots.append(
                    {
                        "night_idx": night_idx,
                        "night_label": label,
                        "show_date": show_date,
                        "venue_id": VENUE_ID,
                        "set_num": set_num,
                        "position": pos,
                        "prev_set": prev_set,
                        "show_id": show_id,
                    }
                )
            prev_set = set_num
    n_slots_total = len(slots)
    print(f"Total slots: {n_slots_total}  (6 nights × {9 + 7 + 2})")

    scorer = load_runtime_scorer(MODEL_PATH)

    # Per-show caches — each show has a fixed (show_date, venue_id) pair,
    # so the stats/ext/bigram artefacts are identical across its 18 slots.
    stats_by_date: dict[str, dict] = {}
    ext_by_date: dict[str, dict] = {}
    bigram_by_date: dict[str, dict] = {}
    for _, show_date, _ in NIGHTS:
        if show_date in stats_by_date:
            continue
        stats_by_date[show_date] = compute_song_stats(
            sim_conn, show_date, VENUE_ID, all_song_ids
        )
        ext_by_date[show_date] = compute_extended_stats(
            sim_conn, show_date, VENUE_ID, all_song_ids
        )
        bigram_by_date[show_date] = compute_bigram_probs(
            sim_conn, cutoff_date=show_date
        )

    # Score matrix: reward[song_i, slot_j] = LightGBM raw score (log-odds).
    # Call the scorer directly rather than predict_next_stateless — the
    # scorer's raw output is already in log-space, so we use it straight
    # as the reward. (predict_next_stateless drops entries with score<=0
    # but those are normal log-odds values meaning "probably not," not
    # "impossible"; treating them as infeasible would force the solver
    # to fill slots with obscure never-played songs to respect the
    # one-per-residency constraint.)
    reward = np.full((k, n_slots_total), NEG_INF, dtype=np.float64)
    for slot_idx, slot in enumerate(slots):
        show_date = slot["show_date"]
        scored = scorer.score_candidates(
            conn=sim_conn,
            show_date=show_date,
            venue_id=slot["venue_id"],
            played_songs=[],
            current_set=slot["set_num"],
            candidate_song_ids=all_song_ids,
            prev_trans_mark=",",
            prev_set_number=slot["prev_set"],
            stats_cache=stats_by_date[show_date],
            ext_cache=ext_by_date[show_date],
            bigram_cache=bigram_by_date[show_date],
        )
        for sid, s in scored:
            si = song_idx_by_id.get(sid)
            if si is None:
                continue
            reward[si, slot_idx] = float(s)

    if args.pace:
        eligible_premium_local_indices = [
            song_idx_by_id[row["song_id"]]
            for row in top_12mo_rows
            if row["song_id"] in song_idx_by_id  # excludes N1-3 plays
        ]
        night_slot_indices: list[list[int]] = [[] for _ in NIGHTS]
        for j, slot in enumerate(slots):
            night_slot_indices[slot["night_idx"]].append(j)
        total_prem_target = len(eligible_premium_local_indices)
        print(
            f"[pace] MILP: {total_prem_target} eligible premiums, "
            f"cap {args.night_cap} per night over {len(NIGHTS)} nights"
        )
        row_ind, col_ind = solve_paced_milp(
            reward,
            premium_song_indices=eligible_premium_local_indices,
            night_slot_indices=night_slot_indices,
            night_cap=args.night_cap,
            total_premiums_target=total_prem_target,
        )
    else:
        # Plain rectangular LAP: pick n_slots_total rows out of k, each
        # matched to a unique column, minimizing total cost.
        row_ind, col_ind = linear_sum_assignment(-reward)

    # row_ind[i] is the song index assigned to column col_ind[i] (== slot i
    # since scipy returns col_ind in 0..n-1 order when n == n_slots_total).
    assignments: list[dict] = []
    for r, c in zip(row_ind, col_ind):
        sid = eligible[r]
        assignments.append(
            {
                "slot_idx": int(c),
                "slot": slots[c],
                "song_id": sid,
                "name": song_names.get(sid, f"#{sid}"),
                "reward": float(reward[r, c]),
            }
        )
    assignments.sort(key=lambda a: a["slot_idx"])

    total_reward = float(reward[row_ind, col_ind].sum())
    # "Positive" = model considers the pick more likely than 50/50
    # (log-odds > 0). Negative scores are normal "unlikely but possible"
    # picks, not infeasible ones.
    positive = sum(1 for a in assignments if a["reward"] > 0.0)
    print(
        f"Total reward (sum of log-odds): {total_reward:.2f}    "
        f"slots with positive log-odds: {positive}/{n_slots_total}"
    )

    by_night: dict[str, list[dict]] = {}
    for a in assignments:
        by_night.setdefault(a["slot"]["night_label"], []).append(a)

    for night_label, show_date, _ in NIGHTS:
        print(f"\n=== {night_label} ({show_date}) ===")
        current_label = None
        for a in by_night[night_label]:
            s = a["slot"]["set_num"]
            label = {"1": "SET 1", "2": "SET 2", "E": "ENCORE"}[s]
            if label != current_label:
                print(f"--- {label} ---")
                current_label = label
            flag = " " if a["reward"] > 0.0 else "."
            print(f"  {a['slot']['position']:>2}.{flag}{a['name']}  ({a['reward']:+.2f})")

    # A-list placements for comparison with the greedy/pacing runs.
    top25_ids = {r["song_id"] for r in top_12mo_rows}
    song_to_night: dict[int, str] = {}
    for a in assignments:
        song_to_night[a["song_id"]] = a["slot"]["night_label"]
    print("\nTop 12-mo favorites — where did the assignment land them?")
    for rank, row in enumerate(top_12mo_rows, start=1):
        sid = row["song_id"]
        name = row["name"]
        where = song_to_night.get(sid, "NOT USED (eligible but not picked)")
        if sid in already_played_ids:
            where = "NOT USED (played N1-3)"
            prefix = "[N1-3]"
        else:
            prefix = "      "
        print(f"  {rank:>2}. {prefix} {name:<38} -> {where}")

    print("\nPer-night pick count:")
    for night_label, _, _ in NIGHTS:
        print(f"  {night_label}: {len(by_night[night_label])} picks")

    # Save JSON alongside the other previews.
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    today = date_type.today().isoformat()
    out_path = PREVIEW_DIR / f"forward-sim-{today}-assign.json"
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_path": str(MODEL_PATH),
        "total_log_prob": total_reward,
        "nights": [
            {
                "label": night_label,
                "show_date": show_date,
                "show_id": show_id,
                "picks": [
                    {
                        "slot_idx": a["slot_idx"],
                        "set": a["slot"]["set_num"],
                        "position": a["slot"]["position"],
                        "song_id": a["song_id"],
                        "name": a["name"],
                        "reward": a["reward"],
                    }
                    for a in by_night[night_label]
                ],
            }
            for night_label, show_date, show_id in NIGHTS
        ],
    }
    out_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nSaved assignment JSON: {out_path}")


if __name__ == "__main__":
    main()
