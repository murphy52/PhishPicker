"""Inspect plays_this_run_count and related features for the Baker's Dozen
Night 13, slot 2 (predicting Rift) — the worst-leak slot.

For each of the top leaky candidates plus a non-leaky reference (Rift itself),
dump the run-awareness features so we can tell whether v10's run detection
correctly saw all 12 prior MSG nights.

If plays_this_run_count >= 1 for prior-played songs, run detection works —
issue is signal weight. If 0, run detection is broken on long residencies.
"""
from pathlib import Path

import numpy as np

from phishpicker.db.connection import open_db
from phishpicker.train.build import build_feature_rows
from phishpicker.train.features import FEATURE_COLUMNS

DB_PATH = Path("data/phishpicker.db")
TEST_SHOW_ID = 1485906108  # 2017-08-06 Baker's Dozen Night 13
PRIOR_SHOW_IDS = [
    1485905830, 1485905853, 1485905879,
    1485905907, 1485905928,
    1485905947, 1485905975, 1485905994,
    1485906014, 1485906036,
    1485906066, 1485906086,
]

conn = open_db(DB_PATH, read_only=True)
song_name = lambda sid: conn.execute("SELECT name FROM songs WHERE song_id=?", (sid,)).fetchone()[0]
song_id_by_name = lambda n: conn.execute("SELECT song_id FROM songs WHERE name=?", (n,)).fetchone()[0]

# How many times was each leaky song played in the prior 12 nights?
leak_names = ["Reba", "Vultures", "Theme from the Bottom", "Stealing Time From the Faulty Plan", "Stash", "Water in the Sky", "Ginseng Sullivan"]
print(f"=== Actual prior-nights play counts (ground truth) ===")
for name in leak_names + ["Rift"]:
    sid = song_id_by_name(name)
    n = conn.execute(
        f"SELECT COUNT(*) FROM setlist_songs WHERE show_id IN ({','.join('?' * len(PRIOR_SHOW_IDS))}) AND song_id=?",
        (*PRIOR_SHOW_IDS, sid),
    ).fetchone()[0]
    print(f"  {name:<42} played {n} time(s) in prior 12 MSG nights")

# Now reconstruct slot-2 context and build features
show = conn.execute("SELECT show_id, show_date, venue_id FROM shows WHERE show_id = ?", (TEST_SHOW_ID,)).fetchone()
setlist = conn.execute(
    "SELECT set_number, position, song_id, trans_mark FROM setlist_songs WHERE show_id = ? ORDER BY set_number, position",
    (TEST_SHOW_ID,),
).fetchall()
all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))

# Simulate up to slot 1 played (slot 2 is the target)
played = [setlist[0]["song_id"]]
slot2 = setlist[1]

feature_rows = build_feature_rows(
    conn,
    show_date=show["show_date"],
    venue_id=show["venue_id"],
    played_songs=played,
    current_set=slot2["set_number"],
    candidate_song_ids=all_song_ids,
    show_id=TEST_SHOW_ID,
    all_show_dates=all_show_dates,
    prev_trans_mark=",",
    prev_set_number=None,
)
rows_by_id = {sid: fr for sid, fr in zip(all_song_ids, feature_rows, strict=True)}

run_feat_idx = {name: FEATURE_COLUMNS.index(name) for name in ["plays_this_run_count", "run_position", "run_length_total", "frac_run_remaining", "shows_since_last_played_anywhere", "plays_last_12mo"]}

print(f"\n=== Feature values at slot 2 of Baker's Dozen Night 13 ===")
print(f"{'song':<42} plays_run  run_pos  run_len  frac_rem  sslpl    p12mo")
for name in leak_names + ["Rift"]:
    sid = song_id_by_name(name)
    fr = rows_by_id[sid]
    vec = fr.to_vector()
    vals = {k: vec[i] for k, i in run_feat_idx.items()}
    print(
        f"  {name:<40} {int(vals['plays_this_run_count']):>8}  "
        f"{int(vals['run_position']):>7}  {int(vals['run_length_total']):>7}  "
        f"{vals['frac_run_remaining']:>8.3f}  "
        f"{int(vals['shows_since_last_played_anywhere']):>5}  "
        f"{int(vals['plays_last_12mo']):>6}"
    )
