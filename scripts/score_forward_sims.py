"""Score forward-sim residency forecasts against the actual setlists.

Run from the api/ directory after a residency completes:
    uv run python ../scripts/score_forward_sims.py \\
        data/previews/forward-sim-2026-04-23.json \\
        data/previews/forward-sim-2026-04-23-paced-0.4.json \\
        data/previews/forward-sim-2026-04-23-paced-0.5.json \\
        data/previews/forward-sim-2026-04-23-paced-0.6.json \\
        data/previews/forward-sim-2026-04-23-paced-0.8.json \\
        data/previews/forward-sim-2026-04-23-paced-1.0.json \\
        data/previews/forward-sim-2026-04-23-assign.json \\
        --out ../docs/retros/sphere-2026.md

Each forward-sim file holds picks for N nights (label, show_date, show_id, picks[]).
Picks have only `name` set (song_id=0, set=""); slots are flat 1..18 with
the convention slots 1-9 = Set 1, 10-16 = Set 2, 17-18 = Encore.

Output: per-variant per-night summary + cross-variant comparison table.
With --out, also writes a markdown retro to that path.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.retro import ActualSlot, load_actual_setlist

STRUCTURE = [("1", 9), ("2", 7), ("E", 2)]


def slot_to_set_pos(slot_idx: int) -> tuple[str, int]:
    """Map flat 1-based slot to (set_number, position) under 9/7/2."""
    cur = 0
    for set_num, n in STRUCTURE:
        if slot_idx <= cur + n:
            return set_num, slot_idx - cur
        cur += n
    return "?", slot_idx - cur


@dataclass
class NightScore:
    label: str
    show_date: str
    show_id: int
    n_pred: int
    n_actual: int
    set_overlap: int  # unique pred song names that appear in actual
    slot_exact: int  # same name at same (set, position)


@dataclass
class VariantScore:
    name: str
    nights: list[NightScore]
    pred_total_unique: int
    actual_total_unique: int
    residency_overlap: int  # unique pred names played anywhere in residency
    right_night_count: int  # pred-name played on the night it was predicted
    pred_song_to_date: dict[str, str]  # song name -> first predicted show_date


def variant_label(path: Path) -> str:
    """Strip the 'forward-sim-DATE-' prefix; return distinguishing tail or 'greedy'."""
    stem = path.stem
    if stem.startswith("forward-sim-"):
        stem = stem[len("forward-sim-") :]
    # Now stem is like "2026-04-23" or "2026-04-23-paced-0.6" or "2026-04-23-assign"
    parts = stem.split("-", 3)
    if len(parts) >= 4:
        return parts[3]
    return "greedy"


def score_variant(path: Path, actuals_by_date: dict[str, list[ActualSlot]]) -> VariantScore:
    raw = json.loads(path.read_text())
    night_scores: list[NightScore] = []
    pred_song_to_night: dict[str, str] = {}
    actual_song_set: set[str] = set()
    pred_song_set: set[str] = set()
    right_night = 0
    played_anywhere = 0

    for night in raw["nights"]:
        date = night["show_date"]
        actual = actuals_by_date.get(date, [])
        actual_by_pos = {(a.set_number, a.position): a.name for a in actual}
        actual_names = {a.name for a in actual}
        actual_song_set.update(actual_names)

        pred_names_this_night: list[str] = []
        slot_exact = 0
        for p in night["picks"]:
            name = p["name"]
            pred_names_this_night.append(name)
            set_num, pos = slot_to_set_pos(p["slot_idx"])
            if actual_by_pos.get((set_num, pos)) == name:
                slot_exact += 1
            if name not in pred_song_to_night:
                pred_song_to_night[name] = date

        pred_unique_this_night = set(pred_names_this_night)
        pred_song_set.update(pred_unique_this_night)
        set_overlap = len(pred_unique_this_night & actual_names)

        night_scores.append(
            NightScore(
                label=night["label"],
                show_date=date,
                show_id=night["show_id"],
                n_pred=len(night["picks"]),
                n_actual=len(actual),
                set_overlap=set_overlap,
                slot_exact=slot_exact,
            )
        )

    for name, pred_date in pred_song_to_night.items():
        if name in actual_song_set:
            played_anywhere += 1
            actual_dates = {
                date for date, slots in actuals_by_date.items()
                if any(s.name == name for s in slots)
            }
            if pred_date in actual_dates:
                right_night += 1

    return VariantScore(
        name=variant_label(path),
        nights=night_scores,
        pred_total_unique=len(pred_song_set),
        actual_total_unique=len(actual_song_set),
        residency_overlap=played_anywhere,
        right_night_count=right_night,
        pred_song_to_date=pred_song_to_night,
    )


def render_stdout(variants: list[VariantScore]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Per-night set overlap (unique predicted songs played that night)")
    lines.append("=" * 78)
    nights = variants[0].nights
    header = f"{'variant':<14}  " + "  ".join(f"{n.label:<8}" for n in nights) + "  total"
    lines.append(header)
    for v in variants:
        per_night = [f"{ns.set_overlap:>2}/{ns.n_pred:<2}" for ns in v.nights]
        total = sum(ns.set_overlap for ns in v.nights)
        total_pred = sum(ns.n_pred for ns in v.nights)
        lines.append(
            f"{v.name:<14}  " + "  ".join(f"{x:<8}" for x in per_night)
            + f"  {total}/{total_pred}"
        )

    lines.append("")
    lines.append("=" * 78)
    lines.append("Per-night slot-exact (same song at same set+position)")
    lines.append("=" * 78)
    lines.append(header)
    for v in variants:
        per_night = [f"{ns.slot_exact:>2}/{ns.n_pred:<2}" for ns in v.nights]
        total = sum(ns.slot_exact for ns in v.nights)
        total_pred = sum(ns.n_pred for ns in v.nights)
        lines.append(
            f"{v.name:<14}  " + "  ".join(f"{x:<8}" for x in per_night)
            + f"  {total}/{total_pred}"
        )

    lines.append("")
    lines.append("=" * 78)
    lines.append("Residency-wide aggregates")
    lines.append("=" * 78)
    lines.append(
        f"{'variant':<14}  {'pred_unique':>11}  {'overlap':>7}  {'right_night':>11}"
    )
    for v in variants:
        lines.append(
            f"{v.name:<14}  {v.pred_total_unique:>11}  "
            f"{v.residency_overlap:>7}  {v.right_night_count:>11}"
        )
    actual_total = variants[0].actual_total_unique if variants else 0
    lines.append(f"\nTotal unique songs actually played across residency: {actual_total}")
    return "\n".join(lines)


def render_per_song_section(
    variants: list[VariantScore],
    actuals_by_date: dict[str, list[ActualSlot]],
) -> list[str]:
    """Per-song catch table: one row per actual song, one col per variant.

    Cell format:
      "—"     not predicted by this variant
      "N4 ✓"  predicted on the night it was actually played
      "N5"    predicted, but on a different night
    """
    lines: list[str] = []

    # Build date -> short label ("N4") from any variant's nights list.
    date_to_label: dict[str, str] = {}
    if variants:
        for n in variants[0].nights:
            short = n.label.replace("Night ", "N")
            date_to_label[n.show_date] = short

    # Walk actuals in date+(set,position) order; one row per (song, first-occurrence).
    seen: set[str] = set()
    actual_song_rows: list[tuple[str, str]] = []  # (name, actual_date)
    for date in sorted(actuals_by_date):
        for s in actuals_by_date[date]:
            if s.name in seen:
                continue
            seen.add(s.name)
            actual_song_rows.append((s.name, date))

    lines.append("## Per-song catch table")
    lines.append("")
    lines.append(
        "One row per song actually played at the Sphere (Nights 4–9). "
        "Cells show the night each variant predicted that song "
        "(`N4 ✓` = right night, `—` = not predicted)."
    )
    lines.append("")
    header = "| Song | Actual | " + " | ".join(v.name for v in variants) + " |"
    sep = "|" + "---|" * (2 + len(variants))
    lines.append(header)
    lines.append(sep)
    for name, actual_date in actual_song_rows:
        actual_short = date_to_label.get(actual_date, actual_date)
        cells = []
        for v in variants:
            pred_date = v.pred_song_to_date.get(name)
            if pred_date is None:
                cells.append("—")
            elif pred_date == actual_date:
                cells.append(f"{date_to_label.get(pred_date, pred_date)} ✓")
            else:
                cells.append(date_to_label.get(pred_date, pred_date))
        lines.append(f"| {name} | {actual_short} | " + " | ".join(cells) + " |")
    lines.append("")

    # Surprises: songs no variant predicted.
    no_variant_caught: list[tuple[str, str]] = []
    for name, actual_date in actual_song_rows:
        if not any(name in v.pred_song_to_date for v in variants):
            no_variant_caught.append((name, actual_date))
    lines.append("### Surprises (songs no variant predicted)")
    lines.append("")
    if no_variant_caught:
        for name, d in no_variant_caught:
            short = date_to_label.get(d, d)
            lines.append(f"- {name} _({short})_")
    else:
        lines.append("- (none — every actual song was predicted by at least one variant)")
    lines.append("")

    return lines


def render_markdown(variants: list[VariantScore], actuals_by_date: dict[str, list[ActualSlot]]) -> str:
    lines: list[str] = []
    lines.append("# Sphere 2026 — Forward-Sim Retrospective")
    lines.append("")
    lines.append(
        f"Compares {len(variants)} forecast variants generated on Night 4 day "
        f"against the actual setlists for Nights 4–9."
    )
    lines.append("")

    if variants:
        nights = variants[0].nights
        lines.append("## Per-night set-level overlap")
        lines.append("")
        lines.append(
            "Of the songs each variant predicted for that night, how many were actually played that night."
        )
        lines.append("")
        header = "| Variant | " + " | ".join(n.label for n in nights) + " | Total |"
        sep = "|" + "---|" * (len(nights) + 2)
        lines.append(header)
        lines.append(sep)
        for v in variants:
            cells = [f"{ns.set_overlap}/{ns.n_pred}" for ns in v.nights]
            total = sum(ns.set_overlap for ns in v.nights)
            total_pred = sum(ns.n_pred for ns in v.nights)
            lines.append(f"| {v.name} | " + " | ".join(cells) + f" | {total}/{total_pred} |")
        lines.append("")

        lines.append("## Per-night slot-exact match")
        lines.append("")
        lines.append("Same song at the same (set, position) — strict positional accuracy.")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for v in variants:
            cells = [f"{ns.slot_exact}/{ns.n_pred}" for ns in v.nights]
            total = sum(ns.slot_exact for ns in v.nights)
            total_pred = sum(ns.n_pred for ns in v.nights)
            lines.append(f"| {v.name} | " + " | ".join(cells) + f" | {total}/{total_pred} |")
        lines.append("")

    lines.append("## Residency-wide aggregates")
    lines.append("")
    lines.append(
        "- **pred_unique**: distinct songs the variant chose across all 6 nights\n"
        "- **overlap**: of those, how many appeared somewhere in the residency\n"
        "- **right_night**: of the overlap, how many were predicted on the night they actually happened"
    )
    lines.append("")
    lines.append("| Variant | pred_unique | overlap | right_night |")
    lines.append("|---|---|---|---|")
    for v in variants:
        lines.append(
            f"| {v.name} | {v.pred_total_unique} | {v.residency_overlap} | {v.right_night_count} |"
        )
    actual_total = variants[0].actual_total_unique if variants else 0
    lines.append("")
    lines.append(f"_Total unique songs actually played across residency: **{actual_total}**_")
    lines.append("")

    lines.extend(render_per_song_section(variants, actuals_by_date))

    lines.append("## Actual setlists (for reference)")
    lines.append("")
    for date in sorted(actuals_by_date):
        slots = actuals_by_date[date]
        lines.append(f"### {date}")
        lines.append("")
        cur_set = None
        for s in slots:
            if s.set_number != cur_set:
                cur_set = s.set_number
                set_label = {"1": "Set 1", "2": "Set 2", "E": "Encore"}.get(
                    str(cur_set).upper(), f"Set {cur_set}"
                )
                lines.append(f"**{set_label}**")
            lines.append(f"- {s.position}. {s.name}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="forward-sim JSON files to score")
    ap.add_argument("--db", default="data/phishpicker.db", help="path to phishpicker.db")
    ap.add_argument("--venue-id", type=int, default=1597, help="venue filter (default Sphere)")
    ap.add_argument("--out", help="optional markdown output path")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 2
    conn = open_db(db_path, read_only=True)

    # Collect distinct dates from all variants and load actuals once.
    dates: set[str] = set()
    for p in args.paths:
        raw = json.loads(Path(p).read_text())
        for n in raw["nights"]:
            dates.add(n["show_date"])

    actuals_by_date: dict[str, list[ActualSlot]] = {}
    missing: list[str] = []
    for d in sorted(dates):
        slots = load_actual_setlist(conn, d, venue_id=args.venue_id)
        if not slots:
            missing.append(d)
        actuals_by_date[d] = slots

    if missing:
        print(
            f"WARN: no setlists found for {missing} (run `phishpicker ingest` first?)",
            file=sys.stderr,
        )

    variants = [score_variant(Path(p), actuals_by_date) for p in args.paths]
    print(render_stdout(variants))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_markdown(variants, actuals_by_date))
        print(f"\nWrote retro markdown: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
