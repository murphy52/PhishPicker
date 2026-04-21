"""Full-show preview for Sphere Night 4 (2026-04-23) under the current model.

Emits two passes:
  (A) raw — trust the run-detection features (plays_this_run_count) to
      organically suppress songs played earlier in the residency.
  (B) filtered — post-filter songs played on Nights 1-3 explicitly.

If the model is doing its job, (A) == (B) and "residency repeats in RAW"
is zero. This is the direct hypothesis test that motivated v10: the
v7-era preview leaked "Also Sprach Zarathustra" (played Night 1) into
Night 4 because its 2-day gap rule misclassified the mid-residency break.

Run from the api/ directory:
    ~/.local/bin/uv run python ../scripts/preview_night4.py

Hardcoded for the 2026 Sphere residency. Adapt RESIDENCY_SHOW_IDS +
SHOW_DATE for later nights.
"""

import json
from datetime import datetime
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.live import advance_set, append_song, create_live_show
from phishpicker.model.scorer import load_runtime_scorer
from phishpicker.predict import predict_next

VENUE_ID = 1597
SHOW_DATE = "2026-04-23"
STRUCTURE = [("1", 9), ("2", 7), ("E", 2)]
RESIDENCY_SHOW_IDS = (1764702178, 1764702334, 1764702381)

MODEL_PATH = Path("data/model.lgb")
READ_DB_PATH = Path("data/phishpicker.db")
LIVE_DB_PATH = Path("data/live.db")
PREVIEW_DIR = Path("data/previews")


def save_preview(picks: list[tuple[str, int, str]], label: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PREVIEW_DIR / f"preview-{SHOW_DATE}.json"
    payload = {
        "show_date": SHOW_DATE,
        "venue_id": VENUE_ID,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model_path": str(MODEL_PATH),
        "pass": label,
        "picks": [
            {"slot_idx": i + 1, "set": set_label, "song_id": sid, "name": name}
            for i, (set_label, sid, name) in enumerate(picks)
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


def run_pass(label: str, apply_filter: bool, already_played: set[int]) -> list[tuple[str, int, str]]:
    scorer = load_runtime_scorer(MODEL_PATH)
    read = open_db(READ_DB_PATH, read_only=True)
    live = open_db(LIVE_DB_PATH)
    show_id = create_live_show(live, SHOW_DATE, VENUE_ID)
    picks: list[tuple[str, int, str]] = []

    header = f"=== preview ({label}) — {SHOW_DATE} — Sphere (Night 4) ==="
    print(header)
    print(f"filtered {len(already_played)} residency songs" if apply_filter else "NO residency filter — model must do the work")
    print()

    for set_num, n_slots in STRUCTURE:
        advance_set(live, show_id, set_num)
        slot_label = {"1": "SET 1", "2": "SET 2", "E": "ENCORE"}[set_num]
        print(f"--- {slot_label} ---")
        for i in range(n_slots):
            cands = predict_next(read, live, show_id, top_n=20, scorer=scorer)
            if apply_filter:
                cands = [c for c in cands if c["song_id"] not in already_played]
            if not cands:
                print(f"  {i + 1:>2}. (no candidates)")
                break
            pick = cands[0]
            alts = ", ".join(c["name"] for c in cands[1:5])
            marker = " *" if pick["song_id"] in already_played else "  "
            print(f"  {i + 1:>2}.{marker}{pick['name']:<32}  (alts: {alts})")
            append_song(live, show_id, pick["song_id"], set_num, ",")
            picks.append((slot_label, pick["song_id"], pick["name"]))
        print()
    return picks


def main() -> None:
    read = open_db(READ_DB_PATH, read_only=True)
    placeholders = ",".join("?" * len(RESIDENCY_SHOW_IDS))
    already_played = {
        r[0]
        for r in read.execute(
            f"SELECT DISTINCT song_id FROM setlist_songs WHERE show_id IN ({placeholders})",
            RESIDENCY_SHOW_IDS,
        ).fetchall()
    }
    read.close()

    picks_raw = run_pass("RAW", apply_filter=False, already_played=already_played)
    saved = save_preview(picks_raw, "RAW")
    print(f"\nSaved preview JSON: {saved}")
    print("\n" + "=" * 70 + "\n")
    picks_filt = run_pass("FILTERED", apply_filter=True, already_played=already_played)

    raw_ids = [p[1] for p in picks_raw]
    filt_ids = [p[1] for p in picks_filt]
    raw_residency_hits = [p for p in picks_raw if p[1] in already_played]

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"raw picks: {len(picks_raw)}   filtered picks: {len(picks_filt)}")
    print(f"residency repeats in RAW: {len(raw_residency_hits)}")
    for set_label, _song_id, name in raw_residency_hits:
        print(f"  -> {set_label}: {name}")
    if raw_ids == filt_ids:
        print("VERDICT: raw == filtered — model organically suppresses residency repeats.")
    else:
        diffs = [(i, r, f) for i, (r, f) in enumerate(zip(raw_ids, filt_ids, strict=False)) if r != f]
        print(f"VERDICT: {len(diffs)} slot(s) diverge — filter is still doing work.")
        for i, r, f in diffs[:10]:
            r_name = next(p[2] for p in picks_raw if p[1] == r)
            f_name = next(p[2] for p in picks_filt if p[1] == f)
            print(f"  slot {i + 1}: raw={r_name} vs filtered={f_name}")


if __name__ == "__main__":
    main()
