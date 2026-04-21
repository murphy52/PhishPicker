"""Forward-simulate Sphere Nights 4-9 under the current model.

For each night in order:
  1. Predict the full show (9/7/2) with no residency filter.
  2. Write the predicted setlist back to a scratch copy of phishpicker.db,
     so the next night's feature builder sees these picks as history.
  3. Report: residency leaks (should be zero if v10 is working), where each
     top 12-mo song lands, per-night picks.

Tests two things:
  - Does v10 suppress residency repeats organically across 6 forward nights?
  - Does v10 "save favorites for later" or front-load the A-list?

Run from the api/ directory:
    ~/.local/bin/uv run python ../scripts/preview_residency.py

Hardcoded for the 2026 Sphere residency. Adapt NIGHTS + PRIOR_RESIDENCY_SHOW_IDS
for future residencies.
"""

import json
import shutil
import sqlite3
from datetime import date as date_type
from datetime import datetime
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.live import advance_set, append_song, create_live_show
from phishpicker.model.scorer import load_runtime_scorer
from phishpicker.predict import predict_next

SIM_DB_PATH = Path("/tmp/sim_residency.db")
REAL_DB_PATH = Path("data/phishpicker.db")
LIVE_DB_PATH = Path("data/live.db")
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

TOP_N = 30  # must exceed STRUCTURE slot count so late-residency nights don't run out


def save_forward_sim(
    all_picks_by_night: dict[str, list[str]],
    night_metadata: list[tuple[str, str, int]],
) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    today = date_type.today().isoformat()
    out_path = PREVIEW_DIR / f"forward-sim-{today}.json"
    nights = []
    for night_label, show_date, show_id in night_metadata:
        names = all_picks_by_night.get(night_label, [])
        picks = [
            {"slot_idx": i + 1, "set": "", "song_id": 0, "name": name}
            for i, name in enumerate(names)
        ]
        nights.append(
            {
                "label": night_label,
                "show_date": show_date,
                "show_id": show_id,
                "picks": picks,
            }
        )
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "model_path": str(MODEL_PATH),
        "nights": nights,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


def main() -> None:
    if SIM_DB_PATH.exists():
        SIM_DB_PATH.unlink()
    shutil.copy(REAL_DB_PATH, SIM_DB_PATH)

    sim_conn = sqlite3.connect(SIM_DB_PATH)
    sim_conn.row_factory = sqlite3.Row

    latest_cutoff = sim_conn.execute(
        "SELECT MAX(show_date) FROM shows WHERE show_date <= '2026-04-19'"
    ).fetchone()[0]
    twelve_mo_ago = "2025-04-19"
    top_12mo = [
        r["name"]
        for r in sim_conn.execute(
            """
            SELECT s.name, COUNT(*) AS n
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
    ]

    already_played_ids = {
        r[0]
        for r in sim_conn.execute(
            f"SELECT DISTINCT song_id FROM setlist_songs WHERE show_id IN ({','.join('?' * len(PRIOR_RESIDENCY_SHOW_IDS))})",
            PRIOR_RESIDENCY_SHOW_IDS,
        ).fetchall()
    }
    print(f"Top-25 songs by plays in last 12mo (through {latest_cutoff}):")
    print("  " + " | ".join(top_12mo[:25]))
    print(f"\nSongs already played Nights 1-3: {len(already_played_ids)}\n")

    song_to_night: dict[str, str] = {}
    all_picks_by_night: dict[str, list[str]] = {}
    total_repeats = 0

    for night_label, show_date, show_id in NIGHTS:
        scorer = load_runtime_scorer(MODEL_PATH)
        live = open_db(LIVE_DB_PATH)
        live_show_id = create_live_show(live, show_date, VENUE_ID)
        picks: list[tuple[str, int, str]] = []
        repeats: list[str] = []

        print(f"=== {night_label} ({show_date}) show_id={show_id} ===")
        for set_num, n_slots in STRUCTURE:
            advance_set(live, live_show_id, set_num)
            slot_label = {"1": "SET 1", "2": "SET 2", "E": "ENCORE"}[set_num]
            print(f"--- {slot_label} ---")
            for i in range(n_slots):
                cands = predict_next(sim_conn, live, live_show_id, top_n=TOP_N, scorer=scorer)
                if not cands:
                    print(f"  {i + 1:>2}. (no candidates)")
                    break
                pick = cands[0]
                song_id, name = pick["song_id"], pick["name"]
                if song_id in already_played_ids:
                    repeats.append(name)
                marker = " *" if song_id in already_played_ids else "  "
                print(f"  {i + 1:>2}.{marker}{name}")
                picks.append((slot_label, song_id, name))
                sim_conn.execute(
                    "INSERT OR REPLACE INTO setlist_songs "
                    "(show_id, set_number, position, song_id, trans_mark) "
                    "VALUES (?, ?, ?, ?, ',')",
                    (show_id, set_num, i + 1, song_id),
                )
                append_song(live, live_show_id, song_id, set_num, ",")
                if name not in song_to_night:
                    song_to_night[name] = night_label
                already_played_ids.add(song_id)
            print()
        sim_conn.commit()
        total_repeats += len(repeats)
        all_picks_by_night[night_label] = [name for _, _, name in picks]
        if repeats:
            print(f"  !! RESIDENCY REPEATS this night: {repeats}")
        print()

    saved = save_forward_sim(all_picks_by_night, NIGHTS)
    print(f"\nSaved forward-sim JSON: {saved}\n")

    print("=" * 70)
    print("RESIDENCY PACING ANALYSIS")
    print("=" * 70)
    print(f"total residency repeats across all 6 nights: {total_repeats}\n")
    print("Top 12-mo favorites — where did the model land them?")
    for rank, name in enumerate(top_12mo[:25], start=1):
        where = song_to_night.get(name, "NOT USED (saved or never fits)")
        played_n1to3 = sim_conn.execute(
            """
            SELECT 1 FROM setlist_songs ss JOIN songs s USING (song_id)
            WHERE ss.show_id IN (?, ?, ?) AND s.name = ? LIMIT 1
            """,
            (*PRIOR_RESIDENCY_SHOW_IDS, name),
        ).fetchone()
        prefix = "[N1-3]" if played_n1to3 else "      "
        print(f"  {rank:>2}. {prefix} {name:<38} -> {where}")
    print("\nPer-night pick count:")
    for night_label, _, _ in NIGHTS:
        names = all_picks_by_night.get(night_label, [])
        print(f"  {night_label}: {len(names)} picks")


if __name__ == "__main__":
    main()
