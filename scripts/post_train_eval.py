"""Post-training evaluation harness — run on Mac mini after a training run finishes.

Reads the freshly-trained artifacts at api/data/{model.lgb, metrics.json,
model.meta.json}, runs the canonical 4/18/2026 Sphere replay, formats a
markdown report comparing aggregate metrics + per-case ranks to the
recorded history of prior versions, and emits a ship/revert recommendation.

Output goes to stdout as Markdown — pipe to a file:
    ssh mac-mini 'cd ~/phishpicker/api && uv run python scripts/post_train_eval.py' \\
        > docs/plans/vN-results.md

The historical comparison numbers are hard-coded from RESUME.md / prior
metrics.json files we no longer have (v5 lives on the NAS, v6 was
overwritten). Update the HISTORY tables when you add a new version.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from phishpicker.config import Settings
from phishpicker.db.connection import open_db
from phishpicker.replay import replay_show
from phishpicker.train.features import FEATURE_COLUMNS

# Show we replay against. 4/18/2026 Sphere — has Buried Alive opener +
# Oblivion set-2 opener + Tweezer Reprise encore, the diagnostic slots
# we've been tracking since v4.
CANONICAL_SHOW_ID = 1764702381
CANONICAL_DATE = "2026-04-18"
CANONICAL_VENUE = "Sphere"

ARTIFACTS_DIR = Path("data")
MODEL_PATH = ARTIFACTS_DIR / "model.lgb"
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"

# Aggregate metrics history. Update this dict when shipping a new version.
HISTORY_AGGREGATE = [
    # (label, top1, top5, mrr, note)
    ("v3", 0.028, 0.128, 0.094, "first real model"),
    ("v4", 0.036, 0.137, 0.104, "+opener-rotation, run-length, jam-vehicle"),
    ("v5", 0.036, 0.145, 0.103, "+album-recency · shipped to NAS"),
    ("v6", 0.036, 0.131, 0.099, "−days_since_debut · refuted, reverted"),
]

# Per-case rank history on the canonical 4/18 Sphere show.
# Slot positions match the actual setlist of that show.
CANONICAL_HISTORY = {
    # slot_idx -> {label: rank}
    1: {"actual": "Buried Alive",      "v0": 45, "v4":  8, "v5": 11, "v6": 14},
    9: {"actual": "Oblivion",          "v0": 47, "v4":  3, "v5":  6, "v6":  5},
    16: {"actual": "Tweezer Reprise",  "v6": 109},  # newer diagnostic slot
}

# Watchlist — features whose gain we want to see in the report regardless
# of where they rank. New features go here when added.
WATCHLIST_FEATURES = (
    "is_set2",
    "is_first_in_set",
    "set2_opener_rate",
    "segue_mark_in",
    "is_cover",
    "bigram_prev_to_this",
)


def fmt_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x*100:.1f}%"


def fmt_rank(r: int | None) -> str:
    if r is None:
        return "—"
    return f"#{r}"


def delta_marker(new: float | int, old: float | int, higher_better: bool = True) -> str:
    """Return a +/- marker for new vs old, with intuitive direction."""
    if isinstance(new, int) and isinstance(old, int):
        d = old - new if higher_better is False else new - old
        if d == 0:
            return "·"
        return f"{'+' if d > 0 else ''}{d}"
    diff = new - old
    if abs(diff) < 0.001:
        return "·"
    sign = "+" if (diff > 0) == higher_better else "−"
    return f"{sign}{abs(diff)*100:.1f}pp"


def print_header(version_label: str, metrics: dict) -> None:
    trained_at = metrics.get("trained_at", "unknown")
    cutoff = metrics.get("cutoff_date", "unknown")
    n_shows = metrics.get("n_shows_trained_on", "?")
    n_groups = metrics.get("n_groups_trained_on", "?")
    n_slots = metrics.get("n_slots", "?")
    n_features = len(metrics.get("feature_columns", []))
    print(f"# {version_label} — Post-training results\n")
    print(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n")
    print(f"- **Trained:** {trained_at}")
    print(f"- **Cutoff:** {cutoff}")
    print(f"- **Trained on:** {n_shows} shows · {n_groups} groups")
    print(f"- **Holdout:** {n_slots} slots across 20 walk-forward folds")
    print(f"- **Features:** {n_features}\n")


def print_aggregate(metrics: dict, version_label: str) -> None:
    print("## Aggregate metrics\n")
    print("| Version | Top-1 | Top-5 | MRR | Notes |")
    print("|---|---|---|---|---|")
    for label, t1, t5, mrr, note in HISTORY_AGGREGATE:
        marker = "" if label != "v5" else "  ← shipped"
        print(f"| {label} | {fmt_pct(t1)} | {fmt_pct(t5)} | {mrr:.3f} | {note}{marker} |")
    new_t1 = metrics["top1"]
    new_t5 = metrics["top5"]
    new_mrr = metrics["mrr"]
    v5_t1, v5_t5, v5_mrr = HISTORY_AGGREGATE[2][1], HISTORY_AGGREGATE[2][2], HISTORY_AGGREGATE[2][3]
    print(
        f"| **{version_label}** | **{fmt_pct(new_t1)}** ({delta_marker(new_t1, v5_t1)}) "
        f"| **{fmt_pct(new_t5)}** ({delta_marker(new_t5, v5_t5)}) "
        f"| **{new_mrr:.3f}** ({delta_marker(new_mrr, v5_mrr)}) "
        f"| this run |"
    )
    t5_ci = metrics.get("top5_ci")
    if t5_ci:
        print(
            f"\n_Top-5 95% CI: [{fmt_pct(t5_ci[0])}, {fmt_pct(t5_ci[1])}]_"
        )
    print()


def print_canonical_replay(conn, version_label: str) -> dict[int, int]:
    """Run replay on the canonical show; return {slot_idx: rank} for v_new."""
    print(f"## Canonical replay — {CANONICAL_DATE} · {CANONICAL_VENUE}\n")
    try:
        result = replay_show(
            conn,
            model_a_path=MODEL_PATH,
            model_b_path=MODEL_PATH,
            show_id=CANONICAL_SHOW_ID,
            top_k=5,
        )
    except Exception as e:
        print(f"_Replay failed: {e}_\n")
        return {}

    print("| Slot | Set | Actual | Top pick | v4 | v5 | v6 | " + version_label + " |")
    print("|---|---|---|---|---|---|---|---|")

    new_ranks: dict[int, int] = {}
    for slot in result["slots"]:
        slot_n = slot["slot"]
        set_n = slot["set"]
        actual = slot["actual_song_name"]
        rank_v_new = slot["rank_a"]
        new_ranks[slot_n] = rank_v_new
        top1 = slot["top_a"][0][1] if slot["top_a"] else "—"

        hist = CANONICAL_HISTORY.get(slot_n, {})

        def cell(label: str) -> str:
            r = hist.get(label)
            return fmt_rank(r) if r is not None else "—"

        # Marker on v_new if it's a top-5 hit
        v_new_cell = fmt_rank(rank_v_new)
        if rank_v_new == 1:
            v_new_cell = f"**{v_new_cell} ✓**"
        elif rank_v_new <= 5:
            v_new_cell = f"**{v_new_cell}**"

        marked_actual = f"_{actual}_"
        print(
            f"| {slot_n} | {set_n} | {marked_actual} | {top1} "
            f"| {cell('v4')} | {cell('v5')} | {cell('v6')} | {v_new_cell} |"
        )

    # Per-case verdict box
    print("\n### Diagnostic slots\n")
    for slot_n in (1, 9, 16):
        if slot_n not in new_ranks:
            continue
        hist = CANONICAL_HISTORY.get(slot_n, {})
        actual = hist.get("actual", "?")
        v5_rank = hist.get("v5")
        v6_rank = hist.get("v6")
        new_rank = new_ranks[slot_n]
        line = f"- **{actual}** (slot {slot_n}): {fmt_rank(new_rank)} under {version_label}"
        if v5_rank:
            line += f" · v5 was {fmt_rank(v5_rank)} ({delta_marker(new_rank, v5_rank, higher_better=False)})"
        if v6_rank:
            line += f" · v6 was {fmt_rank(v6_rank)}"
        print(line)
    print()
    return new_ranks


def print_feature_importance(metrics: dict) -> None:
    print("## Feature-importance gain (top 20 + watchlist)\n")
    importance = metrics.get("feature_importance_gain")
    if not importance:
        print("_metrics.json has no feature_importance_gain field._\n")
        return
    ranked = sorted(importance.items(), key=lambda kv: -kv[1])
    print("| Rank | Feature | Gain | |")
    print("|---|---|---:|---|")
    top_20_names = set()
    for i, (feat, gain) in enumerate(ranked[:20], start=1):
        marker = " ← NEW" if feat in ("is_set2", "is_first_in_set") else ""
        print(f"| {i} | `{feat}` | {gain:,.0f} | {marker} |")
        top_20_names.add(feat)
    # Watchlist features that didn't make top-20
    extras = [(feat, importance[feat]) for feat in WATCHLIST_FEATURES if feat in importance and feat not in top_20_names]
    if extras:
        print("\n_Watchlist below top-20:_\n")
        for feat, gain in extras:
            rank = next(i for i, (f, _) in enumerate(ranked, start=1) if f == feat)
            print(f"- `{feat}` — rank {rank}, gain {gain:,.0f}")
    print()


def print_verdict(metrics: dict, replay_ranks: dict[int, int], version_label: str) -> None:
    print("## Verdict\n")
    new_t5 = metrics["top5"]
    new_mrr = metrics["mrr"]
    v5_t5, v5_mrr = HISTORY_AGGREGATE[2][2], HISTORY_AGGREGATE[2][3]

    ba_rank = replay_ranks.get(1)  # Buried Alive
    obl_rank = replay_ranks.get(9)  # Oblivion
    rep_rank = replay_ranks.get(16)  # Tweezer Reprise

    aggregate_ok = new_t5 >= v5_t5 - 0.005  # within half a point
    aggregate_better = new_t5 > v5_t5 + 0.005
    per_case_ok = (ba_rank is None or ba_rank <= 14) and (obl_rank is None or obl_rank <= 8)
    per_case_better = (ba_rank is not None and ba_rank <= 11) and (obl_rank is not None and obl_rank <= 6)

    verdict_lines: list[str] = []
    if aggregate_better and per_case_better:
        verdict_lines.append(f"### ✅ SHIP — {version_label} clearly beats v5\n")
        verdict_lines.append(f"Both aggregate (Top-5 {fmt_pct(new_t5)} vs v5 {fmt_pct(v5_t5)}) and per-case "
                             f"(BA {fmt_rank(ba_rank)} ≤ v5 #11, Oblivion {fmt_rank(obl_rank)} ≤ v5 #6) improved.\n")
        verdict_lines.append("**Action:** ship to NAS when SSH window is open. Update RESUME.md.")
    elif aggregate_ok and per_case_ok:
        verdict_lines.append(f"### 🟡 INCONCLUSIVE — {version_label} comparable to v5\n")
        verdict_lines.append(f"Top-5 {fmt_pct(new_t5)} vs v5 {fmt_pct(v5_t5)} (within noise). "
                             f"Per-case ranks are also similar.\n")
        verdict_lines.append("**Action:** decide based on what changed and whether it unblocks future work. "
                             "If the slot-type flags meaningfully reshape feature importance, that's a "
                             "structural win even at flat metrics.")
    elif rep_rank is not None and rep_rank < 50:
        verdict_lines.append(f"### 🟡 PARTIAL — {version_label} fixes Tweezer Reprise\n")
        verdict_lines.append(f"Reprise rank {fmt_rank(rep_rank)} (was #109 under v6). "
                             f"Aggregate Top-5 {fmt_pct(new_t5)} vs v5 {fmt_pct(v5_t5)}.\n")
        verdict_lines.append("**Action:** investigate whether the regression is real or noise.")
    else:
        verdict_lines.append(f"### ❌ REGRESSION — {version_label} worse than v5\n")
        verdict_lines.append(f"Top-5 {fmt_pct(new_t5)} vs v5 {fmt_pct(v5_t5)} ({delta_marker(new_t5, v5_t5)}). "
                             f"BA {fmt_rank(ba_rank)}, Oblivion {fmt_rank(obl_rank)}.\n")
        verdict_lines.append("**Action:** revert the experiment, document findings, design next hypothesis.")

    for line in verdict_lines:
        print(line)
    print()


def main() -> int:
    s = Settings()
    conn = open_db(s.db_path)

    # Determine version label — read from CLI arg or default to "v?"
    version_label = sys.argv[1] if len(sys.argv) > 1 else "v?"

    if not METRICS_PATH.exists():
        print(f"# Error: {METRICS_PATH} not found")
        print("Did training finish? Check `tail /tmp/phishpicker-train-*.log`")
        return 1

    metrics = json.loads(METRICS_PATH.read_text())
    # Sanity: confirm runtime FEATURE_COLUMNS matches saved metrics
    saved_cols = metrics.get("feature_columns", [])
    if tuple(saved_cols) != tuple(FEATURE_COLUMNS):
        print(f"# WARNING: schema drift — metrics.json has {len(saved_cols)} cols, runtime has {len(FEATURE_COLUMNS)}")
        print("Replay may fail. Reasons: code edited since training, or wrong artifacts on disk.\n")

    print_header(version_label, metrics)
    print_aggregate(metrics, version_label)
    replay_ranks = print_canonical_replay(conn, version_label)
    print_feature_importance(metrics)
    print_verdict(metrics, replay_ranks, version_label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
