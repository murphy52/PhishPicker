"""Test v10's residency-leak behavior on historical multi-night runs.

For each residency:
  - Take the LAST night (hardest case — most prior songs to suppress).
  - For each slot, build v10 predictions (top-10).
  - Count how many top-10 candidates per slot were played on earlier
    nights of the same residency.
  - Aggregate: leak rate by top-K, worst-slot leak count, actual-song rank.

If v10's walk-until-venue-changes + plays_this_run_count work as
designed, the leak rate should be near zero even for the 13-night
Baker's Dozen (whose shows.run_length column splits it into sub-runs
because of rest days).
"""

from pathlib import Path

import numpy as np

from phishpicker.db.connection import open_db
from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.build import build_feature_rows

MODEL_PATH = Path("data/model.lgb")
DB_PATH = Path("data/phishpicker.db")

RESIDENCIES = [
    # label, ordered list of show_ids (first to last night)
    ("Baker's Dozen 2017 MSG (13 nights)", [
        1485905830, 1485905853, 1485905879,   # 7/21-23
        1485905907, 1485905928,               # 7/25-26
        1485905947, 1485905975, 1485905994,   # 7/28-30
        1485906014, 1485906036,               # 8/01-02
        1485906066, 1485906086, 1485906108,   # 8/04-06
    ]),
    ("Moon Palace 2024-02 (5 nights)", [
        1708468023, 1684286323, 1684286358, 1684286408, 1684286440,
    ]),
    ("Moon Palace 2026-01 (5 nights)", [
        1769552585, 1747245274, 1747245293, 1747245316, 1747245335,
    ]),
]


def leak_check_last_night(conn, scorer, residency_label, show_ids):
    assert len(show_ids) >= 2
    prior_show_ids = show_ids[:-1]
    last_show_id = show_ids[-1]

    prior_song_ids = {
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT song_id FROM setlist_songs WHERE show_id IN ({','.join('?' * len(prior_show_ids))})",
            prior_show_ids,
        ).fetchall()
    }

    show = conn.execute(
        "SELECT show_id, show_date, venue_id FROM shows WHERE show_id = ?", (last_show_id,)
    ).fetchone()
    setlist = conn.execute(
        "SELECT set_number, position, song_id, trans_mark FROM setlist_songs "
        "WHERE show_id = ? ORDER BY set_number, position",
        (last_show_id,),
    ).fetchall()

    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    song_names = {r["song_id"]: r["name"] for r in conn.execute("SELECT song_id, name FROM songs")}
    all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))

    print(f"\n=== {residency_label} ===")
    print(f"  prior nights: {len(prior_show_ids)}   prior unique songs: {len(prior_song_ids)}")
    print(f"  test night show_id={last_show_id} date={show['show_date']} slots={len(setlist)}")

    top3_leaks = 0
    top10_leaks = 0
    total_slot_checks = 0
    worst_slot = None
    worst_leak_count = 0
    actual_ranks = []

    played: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None

    for slot_idx, row in enumerate(setlist, start=1):
        positive = int(row["song_id"])
        feature_rows = build_feature_rows(
            conn,
            show_date=show["show_date"],
            venue_id=show["venue_id"],
            played_songs=played,
            current_set=row["set_number"],
            candidate_song_ids=all_song_ids,
            show_id=last_show_id,
            all_show_dates=all_show_dates,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
        )
        X = np.asarray([fr.to_vector() for fr in feature_rows], dtype=np.float32)
        scores = scorer.score(X)
        order = np.argsort(-scores)
        ranked_song_ids = [all_song_ids[i] for i in order]

        actual_rank = ranked_song_ids.index(positive) + 1
        actual_ranks.append(actual_rank)

        top10 = ranked_song_ids[:10]
        top3 = ranked_song_ids[:3]
        slot_top3_leaks = sum(1 for sid in top3 if sid in prior_song_ids)
        slot_top10_leaks = sum(1 for sid in top10 if sid in prior_song_ids)
        top3_leaks += slot_top3_leaks
        top10_leaks += slot_top10_leaks
        total_slot_checks += 1

        if slot_top10_leaks > worst_leak_count:
            worst_leak_count = slot_top10_leaks
            worst_slot = (slot_idx, row["set_number"], song_names.get(positive, f"#{positive}"), top10)

        played.append(positive)
        prev_trans_mark = row["trans_mark"] or ","
        prev_set_number = row["set_number"]

    print(f"  leak rate top-3: {top3_leaks}/{total_slot_checks * 3} = {top3_leaks / (total_slot_checks * 3):.1%}")
    print(f"  leak rate top-10: {top10_leaks}/{total_slot_checks * 10} = {top10_leaks / (total_slot_checks * 10):.1%}")
    print(f"  actual-song mean rank: {np.mean(actual_ranks):.1f}  MRR: {np.mean([1/r for r in actual_ranks]):.3f}")
    if worst_slot:
        slot_idx, set_num, actual_name, top10 = worst_slot
        leak_names = [song_names.get(sid, f"#{sid}") for sid in top10 if sid in prior_song_ids]
        print(f"  worst slot: #{slot_idx} set {set_num} (actual: {actual_name}) — {worst_leak_count} leaks in top-10: {leak_names}")


def main() -> None:
    conn = open_db(DB_PATH, read_only=True)
    scorer = LightGBMScorer.load(MODEL_PATH)
    for label, show_ids in RESIDENCIES:
        leak_check_last_night(conn, scorer, label, show_ids)


if __name__ == "__main__":
    main()
