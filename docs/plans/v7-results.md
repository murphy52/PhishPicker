# v7 — Post-training results

_Generated 2026-04-21T00:24:50+00:00_

- **Trained:** 2026-04-20T23:51:43.234730+00:00
- **Cutoff:** 2026-04-18
- **Trained on:** 2250 shows · 39395 groups
- **Holdout:** 354 slots across 20 walk-forward folds
- **Features:** 47

## Aggregate metrics

| Version | Top-1 | Top-5 | MRR | Notes |
|---|---|---|---|---|
| v3 | 2.8% | 12.8% | 0.094 | first real model |
| v4 | 3.6% | 13.7% | 0.104 | +opener-rotation, run-length, jam-vehicle |
| v5 | 3.6% | 14.5% | 0.103 | +album-recency · shipped to NAS  ← shipped |
| v6 | 3.6% | 13.1% | 0.099 | −days_since_debut · refuted, reverted |
| **v7** | **6.8%** (+3.2pp) | **21.2%** (+6.7pp) | **0.146** (+4.3pp) | this run |

_Top-5 95% CI: [16.9%, 25.7%]_

## Canonical replay — 2026-04-18 · Sphere

| Slot | Set | Actual | Top pick | v4 | v5 | v6 | v7 |
|---|---|---|---|---|---|---|---|
| 1 | 1 | _Buried Alive_ | The Moma Dance | #8 | #11 | #14 | **#5** |
| 2 | 1 | _AC/DC Bag_ | Kill Devil Falls | — | — | — | **#2** |
| 3 | 1 | _Reba_ | The Moma Dance | — | — | — | #11 |
| 4 | 1 | _Colonel Forbin's Ascent_ | Oblivion | — | — | — | #102 |
| 5 | 1 | _Fly Famous Mockingbird_ | Fly Famous Mockingbird | — | — | — | **#1 ✓** |
| 6 | 1 | _Sigma Oasis_ | Bathtub Gin | — | — | — | #52 |
| 7 | 1 | _Walk Away_ | Back on the Train | — | — | — | #18 |
| 8 | 1 | _Bathtub Gin_ | Bathtub Gin | — | — | — | **#1 ✓** |
| 9 | 2 | _Oblivion_ | Back on the Train | #3 | #6 | #5 | **#4** |
| 10 | 2 | _Simple_ | Chalk Dust Torture | — | — | — | #42 |
| 11 | 2 | _Tweezer_ | Life Saving Gun | — | — | — | #7 |
| 12 | 2 | _Waste_ | Oblivion | — | — | — | #35 |
| 13 | 2 | _Twist_ | First Tube | — | — | — | #13 |
| 14 | 2 | _Run Like an Antelope_ | Piper | — | — | — | #92 |
| 15 | E | _I Am the Walrus_ | First Tube | — | — | — | #102 |
| 16 | E | _Tweezer Reprise_ | A Life Beyond The Dream | — | — | #109 | #7 |

### Diagnostic slots

- **Buried Alive** (slot 1): #5 under v7 · v5 was #11 (+6) · v6 was #14
- **Oblivion** (slot 9): #4 under v7 · v5 was #6 (+2) · v6 was #5
- **Tweezer Reprise** (slot 16): #7 under v7 · v6 was #109

## Feature-importance gain (top 20 + watchlist)

| Rank | Feature | Gain | |
|---|---|---:|---|
| 1 | `bigram_prev_to_this` | 401,687 |  |
| 2 | `is_first_in_set` | 88,181 |  ← NEW |
| 3 | `plays_last_12mo` | 63,214 |  |
| 4 | `shows_since_last_played_anywhere` | 14,590 |  |
| 5 | `days_since_last_played_anywhere` | 10,866 |  |
| 6 | `days_since_debut` | 8,095 |  |
| 7 | `shows_since_last_any_opener_role` | 7,337 |  |
| 8 | `debut_year` | 7,131 |  |
| 9 | `avg_set_position_when_played` | 6,756 |  |
| 10 | `total_plays_ever` | 6,308 |  |
| 11 | `set_position` | 5,930 |  |
| 12 | `prev_song_id` | 4,983 |  |
| 13 | `played_already_this_run` | 3,524 |  |
| 14 | `tour_closer_rate` | 3,317 |  |
| 15 | `tour_opener_rate` | 3,315 |  |
| 16 | `tour_position` | 3,182 |  |
| 17 | `set1_opener_rate` | 3,108 |  |
| 18 | `encore_rate` | 3,039 |  |
| 19 | `era` | 2,830 |  |
| 20 | `closer_score` | 2,800 |  |

_Watchlist below top-20:_

- `is_set2` — rank 32, gain 826
- `set2_opener_rate` — rank 40, gain 71
- `segue_mark_in` — rank 44, gain 0
- `is_cover` — rank 41, gain 5

## Verdict

### ✅ SHIP — v7 clearly beats v5

Both aggregate (Top-5 21.2% vs v5 14.5%) and per-case (BA #5 ≤ v5 #11, Oblivion #4 ≤ v5 #6) improved.

**Action:** ship to NAS when SSH window is open. Update RESUME.md.

