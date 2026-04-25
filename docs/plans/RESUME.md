# Resume Point — 2026-04-21 (v10 shipped)

## This session's work (2026-04-21)

Executed the v10 retrain + deploy decided at end of session 3. Chose
**Path B** (ship with run-detection fix + `plays_this_run_count` only;
defer `run_saturation_pressure` to v11 pending real-world residency data).

### Deploy outcome

- **NAS now serves v10.** HEAD `6e09092`, `scorer: "lightgbm"` verified
  via `/api/meta` healthcheck.
- **Prior state preserved** as `data/*.prev-backup` on NAS (rollback is
  one command, see below).
- **Training: 3h 25m** on Mac mini (slightly faster than v7's 3h 26m).
  Cutoff `2026-04-19` — keeps the Sphere residency itself out of training.

### Aggregate metrics — v10 vs v7 (n=354)

| Metric | v10 | v7 | Δ | Within 95% CI? |
|---|---|---|---|---|
| Top-1 | 5.4% | 6.8% | −1.4pp | Yes, v10 CI [3.1, 7.9] |
| Top-5 | 21.8% | 21.2% | +0.6pp | Yes, v10 CI [17.8, 26.3] |
| MRR | 0.140 | 0.146 | −0.006 | Yes |
| Top-20 | 43.2% | — | — | — |

**Aggregate is statistically indistinguishable from v7.** Baselines
unchanged (random 0.57%, frequency 3.95%, heuristic 2.26% Top-5) —
holdout difficulty is the same.

### Feature-importance shift

- `plays_this_run_count` landed at gain **3,350** (rank ~15 of 42) —
  non-trivial; the model is using it.
- `plays_last_12mo` **jumped 62,911** (v7: 16,935, 3.7×). With
  `plays_this_run_count` present, the tree leans much harder on 12-mo
  play rate as a complementary residency signal.
- `bigram_prev_to_this` 401,862 (v7: 261,757) — still the dominant signal.
- `is_first_in_set` 88,912 (≈v7). Run-geometry features
  (`run_position` 560, `run_length_total` 1,405, `frac_run_remaining` 726)
  stayed low — **the play-count feature is carrying the residency axis,
  not geometry.**

### Residency validation (the whole point of v10)

Ran `phishpicker replay` v10-vs-v10 on Sphere Night 2 (show_id
1764702334) and Night 3 (1764702381). Cross-checked top-3 predictions
against prior-night setlists:

- **Zero** Night-1 songs appeared in any Night-2 top-3 prediction (19 slots).
- **Zero** Night-1 or Night-2 songs appeared in any Night-3 top-3
  prediction (16 slots).

`plays_this_run_count` is actively down-ranking prior-residency-night
plays. This is the behavior v10 was built for, and it's working.

### Per-case: Night 3 spot-check vs v7 published ranks

| Song | v7 | v10 | Δ |
|---|---|---|---|
| Buried Alive (opener) | 5 | **1** | +4 ⬆️ |
| Oblivion (set-2 opener) | 4 | **1** | +3 ⬆️ |
| Tweezer Reprise (encore) | 7 | 12 | −5 ⬇️ |

2-of-3 headline-song ranks improved dramatically. Tweezer Reprise
regressed slightly but is still vastly better than pre-v7 (#109).

### Per-show walk-forward (from training log, walk-forward folds)

| Fold | Predicts | Slots | Top-1 | Top-5 |
|---|---|---|---|---|
| 18 | Night 2 (4/17) | 17 | 0.000 | 0.176 |
| 19 | Night 3 (4/18) | 19 | 0.105 | 0.211 |
| 20 | next-in-DB after Night 3 | 16 | 0.125 | 0.375 |

Sphere shows are **easier than the aggregate** (Night 2 replay MRR 0.247,
Night 3 replay MRR 0.390 vs aggregate 0.140) — unsurprising given the
bigram structure Phish uses heavily on residency nights.

### Post-deploy exploration (same session)

After shipping, ran three follow-up tests that sharpened our understanding
of v10's residency behavior.

#### 1. Night 4 preview — `scripts/preview_night4.py` (commit `a9aec79`)

Runs two passes: RAW (no residency filter) and FILTERED (post-filter
songs played Nights 1-3). If `plays_this_run_count` is doing its job,
the outputs match. **Result: raw == filtered, zero residency repeats.**
All 52 Nights-1-3 songs are organically suppressed. The v7-era bug
("Also Sprach Zarathustra" predicted for Night 4 despite being played
Night 1) is gone.

#### 2. 6-night forward simulation — `scripts/preview_residency.py` (commit `e10dda4`)

Forward-simulates Nights 4-9 by writing each night's predicted setlist
back to a scratch DB copy so the next night's feature builder sees it.
**Result: 0 residency repeats across all 6 nights.** v10 front-loads
A-list into N4-6 (Moma Dance, Stash, Sand, Chalk Dust Torture, Slave to
the Traffic Light) and reaches into deeper catalog by N7-9 (Runaway Jim,
NICU, Cars Trucks Buses, Llama). "Deplete A-list early, then B-list"
rather than "evenly spread A-list across the run." Whether this matches
Phish's actual pacing is an open question until Thursday.

#### 3. Historical residency leak test — `scripts/historical_residency_leak_test.py` + `leak_debug_bakers_dozen.py` (commit `7cb2159`)

Picked the last night of three historical residencies, counted how many
top-K candidates per slot were played on earlier nights of the same run.

| Residency | Prior nights | Top-3 leak | Top-10 leak | Actual MRR |
|---|---|---|---|---|
| Moon Palace 2026-01 (5 nights) | 4 | **0.0%** | **0.0%** | 0.120 |
| Moon Palace 2024-02 (5 nights) | 4 | **0.0%** | 0.5% | 0.154 |
| **Baker's Dozen 2017 MSG (13 nights)** | **12** | **10.0%** | **23.0%** | 0.088 |

**Baker's Dozen leaks heavily.** Feature-value debug at the worst slot
confirmed run detection works correctly (`plays_this_run_count=1` for
every prior-played song, `run_position=13`, `run_length_total=13`). The
issue is **signal weight, not detection**: `plays_this_run_count=1` can't
distinguish "1x in 3-night run" (loose constraint) from "1x in 13-night
run" (strict constraint), so the model's learned suppression is
calibrated to the common short-residency case and gets overwhelmed by
`plays_last_12mo` and bigram completion at long runs.

**Diagnosis converts `run_saturation_pressure` from "maybe" to
"mechanically motivated" for v11.** The formula
`(plays_last_12mo / shows_last_12mo) × (run_position − 1) − plays_this_run_count`
provides a direct scaling axis: at run_position=13, a 12-mo favorite
with plays_this_run_count=1 becomes strongly overdue-negative (expected
~8, actual 1); at run_position=2, the same value is only mildly
negative.

**For Sphere (max 8 prior nights by N9):** expect clean top-1 picks
(confident bigram/slot-type signals dominate) and growing top-10 leaks
as the run progresses. Not catastrophic but observable.

### Nightly-smoke cron (same session)

Installed on Mac mini: `0 12 * * *` runs `phishpicker nightly-smoke`
daily at noon EDT, defaulting to "yesterday UTC". Logs to
`~/phishpicker-smoke.log`; JSONL at
`~/phishpicker/api/data/nightly-predictions.jsonl`.

Nights 1-3 backfilled into the JSONL as pre-Sphere baseline:

| Date | Show | Slots | Median rank | Top-1 | Top-5 |
|---|---|---|---|---|---|
| 2026-04-16 | Night 1 Sphere | 17 | 7 | 3/17 | 7/17 |
| 2026-04-17 | Night 2 Sphere | 19 | 20 | 3/19 | 7/19 |
| 2026-04-18 | Night 3 Sphere | 16 | 6 | 5/16 | 8/16 |

Thursday's Night 4 will auto-log at 12pm EDT Friday.

### Mac mini cleanup (side quest)

Mac mini was 14 commits behind origin/main with ~163 lines of orphaned
uncommitted edits (experimental `days_since_debut` re-adds from an
earlier session, superseded by shipped code). Everything stashed as
`stash@{0}: mac-mini pre-v10-pull orphaned edits 2026-04-20`.

**Untouched on Mac mini**: `wait_then_train_v2.sh`, `wait_then_train_v4.sh`
(scratch training-wait helpers, captured in the stash). Drop the stash
when you're sure those aren't needed.

### Commits (all pushed; v10 family + post-deploy exploration)

| SHA | Summary |
|---|---|
| `7cb2159` | **feat(scripts): historical residency leak test + plays_this_run_count debug** |
| `e10dda4` | feat(scripts): preview_residency — 6-night forward simulation N4-N9 |
| `a9aec79` | feat(scripts): preview_night4 — with/without residency filter |
| `a6875cf` | docs: RESUME — v10 shipped to NAS, headline metrics + residency validation |
| `6e09092` | docs: RESUME handoff — v10 run-detection fix + plays_this_run_count shipped |
| `ec023a3` | **feat(train): v10 — plays_this_run_count replaces binary** |
| `d31ff84` | **fix(stats): walk-until-venue-changes for run detection** |
| `b09e76a` | docs: v10 plan — residency / run awareness |
| `3eaa864` | docs: RESUME.md update for next session pickup |

### NAS rollback command (one step)

```bash
ssh Murphy52@storage.local "cd '/home/Murphy52/docker/apps/phishpicker' && \
  git reset --hard 77960a4a3fe739c4ed8234bdf08cdf933175c2f7 && \
  cd data && cp model.lgb.prev-backup model.lgb && \
  cp model.meta.json.prev-backup model.meta.json && \
  cp metrics.json.prev-backup metrics.json && cd .. && \
  docker compose build api && docker compose up -d api"
```

## What's next

### Sphere residency progress (mid-run, 2026-04-25)

| Date | Night | Status |
|---|---|---|
| Thu 2026-04-23 | Night 4 | played; smoke logged |
| Fri 2026-04-24 | Night 5 | played; smoke logged |
| Sat 2026-04-25 | Night 6 | tonight |
| Thu 2026-04-30 | Night 7 | upcoming |
| Fri 2026-05-01 | Night 8 | upcoming |
| Sat 2026-05-02 | Night 9 | upcoming |

Real-world v10 results so far (from `~/phishpicker/api/data/nightly-predictions.jsonl`):

| Night | Slots | Median rank | Top-1 | Top-5 |
|---|---|---|---|---|
| N4 (4/23) | 18 | 20 | 1/18 | 5/18 |
| N5 (4/24) | 18 | **65** | 1/18 | 1/18 |

N5's median rank 65 is exactly the long-run signal-weight collapse the
Baker's Dozen leak test predicted — early empirical support for v11's
`run_saturation_pressure`.

### Pacing-experiment scoring (2026-04-25)

Scored the seven cached forward-sim variants from `api/data/previews/`
(generated 2026-04-23) against N4 + N5 actuals. **Paced-0.6 wins** by
a clear margin on bag-of-songs coverage:

| Variant | N4 hits | N5 hits | Combined |
|---|---|---|---|
| **paced-0.6** | **6/17 (35%)** | **5/18 (28%)** | **11/35 (31%)** |
| greedy (baseline) | 3/17 | 5/18 | 8/35 (23%) |
| paced-0.8 / paced-1.0 | 3/17 | 2/18 | 5/35 (14%) |
| assign (LAP/MILP) | 4/17 | 1/18 | 5/35 (14%) |
| paced-0.4 / paced-0.5 | 2/17 / 0/17 | 0/18 / 2/18 | 2/35 (6%) |

(N4 had 17 unique songs in 18 slots — Fuego sandwiched at slots 10/12.)

Slot-exact matching is ~0 across all variants — order accuracy is a
different problem from setlist accuracy. Scorer is currently at
`/tmp/score_pacing.py`; should be moved to `scripts/` and wired to
nightly-smoke so each new night auto-scores. Open work item.

### Sandwich repeats fix (2026-04-25, commit `63b3ac6`)

Discovered that **~34% of historical shows contain at least one Phish
sandwich** (same song twice in a show, e.g. Fuego→Golden Age→Fuego on
N4 set 2). v10's feature pipeline was double-counting all of them.

Fixed in three files (TDD'd, full suite 319 passing):
- `bigrams.py`: dedupe `(show, set, song)` with MIN(position) before
  extracting transitions. Drops the spurious sandwich-return bigram
  (B→A from A→B→A) that was diluting B's true successor distribution.
  Affects model's #1 feature (`bigram_prev_to_this`, gain 401K).
- `model/stats.py`: `total_plays_ever`, `times_played_last_12mo`,
  `plays_this_run_count`, opener/encore role counts → `COUNT(DISTINCT
  show_id)`. The `plays_this_run_count` fix directly tightens v10's
  residency-suppression mechanism.
- `train/extended_stats.py`: new `song_show` CTE collapses `(show,
  song)` while preserving role flags via MAX(CASE...). Affects
  `plays_last_6mo`, `recent_play_acceleration`, `times_at_venue`,
  set/encore/closer role rates, `avg_set_position_when_played`.

Code-only — takes effect at next retrain (v11). Bundled into the v11
candidate list below.

### v11 plan — post-Sphere, bundle three feature/correctness changes

The Baker's Dozen test + N5 result upgraded `run_saturation_pressure`
from "speculative" to **mechanically motivated**. v11 candidate list:

1. **`run_saturation_pressure`** — `(plays_last_12mo / shows_last_12mo)
   × (run_position − 1) − plays_this_run_count`. Addresses long-run
   signal-weight degradation. N5 result strengthens the case.
2. **`slots_into_current_set`** — 1-indexed position within current set
   (not global slot number). Addresses v7-residual-analysis set-2
   closer misses (Antelope tied for #1 historical set-2 closer but v7
   ranked it #92). See `docs/plans/v7-residual-analysis.md`.
3. **Sandwich-repeat dedupe** (commit `63b3ac6`, code-only — already
   on main). Counts and bigrams now treat sandwiches as one play.

All three are cheap TDD + walk-forward cycles. Target retrain after
Sphere residency concludes (post 2026-05-02), using Night 4-9 outcomes
as the validation signal.

### Phish DB show_ids (for replay)

- Night 1: 1764702178 (4/16)
- Night 2: 1764702334 (4/17)
- Night 3: 1764702381 (4/18)
- Night 4: 1764702416 (4/23) — setlist ingested
- Night 5: 1764702441 (4/24) — setlist ingested
- Night 6: 1764702466 (4/25) — tonight
- Night 7: 1764702491 (4/30)
- Night 8: 1764702513 (5/1)
- Night 9: 1764702539 (5/2)

## Prior context (v7 baseline)

✅ **v7 shipped to NAS and serving.** Top-5 14.5% → 21.2%, Top-1 nearly 2×.
✅ **v8 code cleanup committed** (`fd44f67`). Not yet trained — v9 candidate.
✅ **Residual-miss analysis** written up (`65ce024`), proposes v9 feature.

## TL;DR for next session

- **v7 trained on Mac mini in 3h 26m** (faster than v6's 6h 52m). Artifacts
  at `~/phishpicker/api/data/{model.lgb, metrics.json, model.meta.json}`.
- **Aggregate (n=354 holdout slots):**
  - Top-1: **6.8%** (v5: 3.6%, +3.2pp · nearly 2×)
  - Top-5: **21.2%** (v5: 14.5%, +6.7pp · CI [16.9, 25.7] excludes v5)
  - MRR: **0.146** (v5: 0.103, +43%)
- **Per-case 4/18 Sphere replay:**
  - Buried Alive: #5 (v5 #11, v6 #14, v4 #8)
  - Oblivion: #4 (v5 #6, v6 #5, v4 #3)
  - **Tweezer Reprise: #7 (v6 #109)** — hugely improved despite no cross-slot
    bigram feature; the slot-type flags are doing the work
- **Sanity-check passed:** baselines (random/freq/heuristic) are flat between
  v6 and v7 → holdout difficulty unchanged → the model lift is real.
- **Feature importance shifts:** `is_first_in_set` jumped to **rank 2 by
  gain (88K)**, just below `bigram_prev_to_this`. `is_set2` modest at rank
  32. `set2_opener_rate` still tiny (rank 40, gain 71) — it's no longer 0
  but the slot-type flag absorbed most of the work.
- **NAS still serves v5.** v7 is on Mac mini only. **Ship action pending.**

## Deploy status

- ✅ v7 live on NAS (commit `77960a4`, `scorer:lightgbm` confirmed).
- ✅ All commits pushed to origin/main.
- Backups on NAS:
  - `data/*.v5-backup` — sticky v5 artifacts for emergency deep rollback
  - `data/*.prev-backup` — last pre-deploy snapshot (currently v5, since
    that's what was live before v7)
- Deploy script: `scripts/deploy_to_nas.sh` — generic code+model deploy
  with pre-flight + healthcheck + rollback one-liner for future versions.

## v8 cleanup — code landed, not trained

Commit `fd44f67` (42 features, down from 47):

- **segue_mark_in** — lookup now strips whitespace. Was always 0 pre-v8
  because DB has `' > '`/`' -> '` with spaces but the map had bare keys.
  Real variance in the DB (33% jam-inline `>`, 5% segue `->`) is now
  reaching the model.
- **is_cover** — new `PHISH_FAMILY_ARTISTS` whitelist in extended_stats.py
  ({Phish, Trey Anastasio, Mike Gordon, Page McConnell, Jon Fishman}).
  Pre-v8 logic `1 if original_artist else 0` flagged Phish originals as
  covers. Now: family=0, real third-party covers=1, NULL=0.
- Dropped 5 features: `historical_gap_mean`, `middle_of_set_2_score`,
  `shows_since_last_played_this_run`, `opener_score`, `encore_score`.
  First 3 were never populated; last 2 were redundant with extended-stats
  refinements. `opener_score`/`encore_score` stay on SongStats for the
  heuristic scorer. LightGBM side now has 42 lean features.
- Tests: 201 pass (3 new).

v8 will become v9-the-model on the next training run. The code is on
`main` but no training has been kicked off. NAS still runs the v7 model
+ v7 code combination (47 features). Schema-mismatch check in the deploy
script will prevent an accidental ship of a v8-code + v7-model combo.

## v10 feature family queued — residency / run awareness

`docs/plans/2026-04-20-residency-run-awareness.md` details a run-
detection rewrite plus a family of run-aware features motivated by
the Sphere Night 4 preview:

- **Run detection**: replace `_RUN_MAX_GAP_DAYS=2` gap heuristic with a
  walk-until-venue-changes rule (still intersected with `tour_id` for
  safety). Immediate win without retraining — fixes
  `played_already_this_run` for mid-residency gaps (Sphere 4/18→4/23).
- **New features**: `run_length_scheduled`, `nights_remaining_in_run`,
  `plays_this_run_count` (integer, replacing binary), `is_residency`,
  `run_saturation_pressure` (per-song overdue-within-residency score).

Motivated by v7 preview picking `Also Sprach Zarathustra` on Night 4
after it was played on Night 1 — model had no way to see Night 1 as
part of the same run, and no concept of "Phish saves favorites across
9 nights rather than blowing them on Night 1."

## v9 experiment queued — from residual analysis

`docs/plans/v7-residual-analysis.md` proposes one concrete feature add
for v9:

- **`slots_into_current_set`** — 1-indexed position within the current
  set (not the global slot number). Caller tracks it analogously to
  `prev_set_number`. Expected to help set-2 closers (Antelope tied for
  #1 historical set-2 closer but v7 ranked it #92 on 4/18 — no "approaching
  closer territory" signal in the feature set).

The analysis categorizes v7's residual misses:
- **Bustouts** (Forbin's 2.3yr gap, #102) — fundamentally unpredictable
- **Surprise covers** (Walk Away with Joe Walsh, Walrus) — external info
- **Set-2 closers** — tractable, `slots_into_current_set` should help

## Next-session priorities

1. **Train v9** on Mac mini when ready (expect 3-4h based on v7 timing).
   Use `phishpicker train run --cutoff 2026-04-18` for apples-to-apples
   with v7. Artifacts land on Mac mini; use `scripts/post_train_eval.py`
   for the results report.
2. **Add `slots_into_current_set`** (BEFORE retraining, if going that
   route) following the TDD + prev_set_number plumbing pattern from v7.
3. **Or**: skip v9 feature-add and just retrain with v8 to see how the
   bug-fixed `segue_mark_in` + cleaner `is_cover` shift metrics alone.
   Arguably a cleaner A/B than bundling a new feature.
4. **Deploy**: `bash scripts/deploy_to_nas.sh` with NAS SSH window open.
   Prefer `NAS_HOST='Murphy52@storage.local'` (LAN) — Cloudflare tunnel
   token needs re-login to work. Rollback documented in script header.
5. **Deferred still**: nightly-smoke cron on Mac mini (build up a live track
  record of v7's real-world accuracy).

## Commits this session (most recent first, all pushed)

| SHA | Summary |
|---|---|
| 65ce024 | docs: v7 residual miss analysis — categorizes + proposes v9 feature |
| fd44f67 | **feat(train): v8 cleanup — fix segue_mark_in + is_cover bugs, drop 5 dead features** |
| 7c0e017 | docs: v7 is live on NAS |
| 77960a4 | ops: deploy_to_nas.sh — true code+model deploy with verification |
| 43696cf | ops: ship_v7_to_nas.sh + RESUME.md update (superseded) |
| b630159 | docs(v7): results report + post-train eval harness + reader guide |
| e746975 | feat(train): add `is_set2` + `is_first_in_set` slot-type flags |
| 2632ef6 | docs: record v6 outcome — hypothesis refuted, reverted |
| ee53da8 | revert: restore `days_since_debut` — v6 hypothesis refuted |
| dd811a2 | docs: RESUME.md update for next session pickup |
| 3d6c95e | revert: drop `days_since_debut` (v6 hypothesis test) |
| 3931b55 | feat: album-recency batch (B1 + B2 + B3) — v5 run |
| 167892e | tune: raise BUSTOUT_THRESHOLD_SHOWS 50→100; days-vs-shows note |
| b88dc0a | merge: nightly-smoke harness (subagent) |
| (merge)  | merge: model-vs-model replay CLI (subagent) |
| b88aec0 | docs: signal research from 4/18-4/19 domain-expert session |
| 373b088 | feat: opener-rotation + warm-up-fit + run-length + relaxed run detect |
| f3c7599 | perf: fuse 7 extended_stats queries into 1 CTE |
| cadcaed | fix: rank positive against all songs, not just not-yet-played |
| 5a747eb | fix: skip future-dated empty shows in walk-forward + cutoff |
| ... | (see git log) |

All pushed to `https://github.com/murphy52/PhishPicker`.

## Model evolution

| Version | Features added | Top-1 | Top-5 | MRR | Notes |
|---|---|---|---|---|---|
| v0 (old mixed-artist) | — | 6.8% | 16.8% | 0.132 | mixed-artist noise, old fixture |
| v1 (Phish-only) | artist_id filter | 2.8% | 11.7% | 0.090 | half the data, drop in Top-1 |
| v3 (shipped) | +extended, tour-rotation, segue | 2.8% | 12.8% | 0.094 | |
| v4 (shipped) | +opener rotation, warm-up-fit, run-length, relaxed run | **3.6%** | 13.7% | **0.104** | +29% Top-1 vs v3 |
| v5 (shipped NAS) | +album recency (B1-B3) | 3.6% | **14.5%** | 0.103 | +Top-5 but BA/Oblivion regressed |
| v6 (refuted) | −days_since_debut | 3.6% | 13.1% | 0.099 | strictly worse — reverted |

Headline metrics are bounded by n=358 holdout slots (CI on Top-1 ≈ ±2pp).
v6 Top-5 CI [10.1, 16.5] overlaps v5 14.5% — the aggregate regression is
directional but within one CI. Combined with per-case results, though,
the verdict is clear.

### Per-case validation (4/18 Sphere opener + set-2 opener)

| Slot | Actual | v0 | v4 | v5 | v6 |
|---|---|---|---|---|---|
| 4/18 opener | Buried Alive | #45 | #8 | #11 | **#14** |
| 4/18 set-2 opener | Oblivion | #47 | #3 | #6 | **#5** |

v6 hypothesis: dropping `days_since_debut` should recover Buried Alive/
Oblivion ranks without losing v5's +0.8pp Top-5 lift.

**Result: hypothesis refuted.** Buried Alive got *worse* (#11 → #14), Oblivion
marginally better within n=2 noise (#6 → #5), Top-5 regressed. Dropping
`days_since_debut` is not the right lever.

### v6 feature-importance shifts (for next-experiment context)

With `days_since_debut` gone, its 16k gain partially redistributed:
- `debut_year`: 28.6k → 32.4k (+13%) — absorbed some, not all
- `prev_song_id`: 28.9k → 24.4k (-16%) — *decreased* unexpectedly
- `set_position`: 27.3k → 31.3k (+15%)
- `bigram_prev_to_this`: 261.8k → 259.5k (~flat, still 8× everything)

So debut-era signal did compress into `debut_year` somewhat, but net gain
was lost (combined 45k → 32k). And the drop shook up `prev_song_id`'s
contribution in a way that hurt opener prediction specifically.

## Feature landscape (post v5, feature_importance_gain)

**Top signal drivers:**
1. `bigram_prev_to_this` — 261,757 gain (8x anything else — Mike's→Hydrogen→Weekapaug)
2. `prev_song_id` — 28,928
3. `debut_year` — 28,592
4. `set_position` — 27,285
5. `days_since_last_played_anywhere` — 22,124
6. `current_set` — 21,333
7. `plays_last_12mo` — 16,935
8. `days_since_debut` — 16,380 (dropped in v6 as redundant)
9. `total_plays_ever` — 11,558
10. `avg_set_position_when_played` — 11,232

**Weak / zero gain:**
- `segue_mark_in` — 0 (suspicious; training data may lack variance)
- `historical_gap_mean`, `middle_of_set_2_score` — 0 (never populated)
- `set2_opener_rate` — 122 (gain is low globally but it matters a lot for
  set-2-opener slots specifically — split-level importance would tell us
  more than aggregate gain)

## Infrastructure

- **Repo**: https://github.com/murphy52/PhishPicker (main)
- **Mac mini** (`ssh mac-mini`, Administrator's-Mac-mini.local):
  - `~/phishpicker/` clone at main
  - `uv` managed Python 3.12, libomp via Homebrew
  - `.env` in `~/phishpicker/api/.env` (copy of repo root's)
  - Training logs: `/tmp/phishpicker-train-v{N}.log`
  - DB: `~/phishpicker/api/data/phishpicker.db` (2250 Phish-only shows,
    39405 setlist rows, 976 songs; 4/18 setlist ingested via fresh
    `phishpicker ingest` run 2026-04-20 for v6 replay)
  - Artifacts: `~/phishpicker/api/data/{model.lgb, model.meta.json, metrics.json}`
- **NAS** (`Murphy52@storage.local` OR `nas-ssh` via Cloudflare):
  - LAN SSH sometimes refused — SSH window is manually opened for
    6-hour periods. Cloudflared tunnel is alternative.
  - Docker compose stack at `/home/Murphy52/docker/apps/phishpicker/`
  - Currently serves **v5** at loopback `127.0.0.1:3400`
  - DB + artifacts at `/home/Murphy52/docker/apps/phishpicker/data/`
  - 4/17 setlist manually inserted via `/tmp/phishpicker-insert-4-17.sql`;
    4/18 setlist NOT yet in NAS DB

## Playbook for the next session

The v6 branch of experiments is closed. Main is aligned with v5, which
is shipped on NAS. Below are **candidate next experiments** ranked by
expected information value. Pick one; don't just sequence through.

### Experiment A (recommended): try dropping `debut_year` instead

Symmetric test of the redundancy hypothesis. v5 had both `debut_year` (gain
28.6k) and `days_since_debut` (16.4k). v6 dropped the smaller one and lost
aggregate. v7 would drop the larger one (`debut_year`), keeping the
date-granular `days_since_debut`.

Rationale: if the pair really is redundant, dropping either should give
similar metrics. If v7 ≈ v5, redundancy confirmed and we pick the cheaper
feature. If v7 < v5 by a similar margin to v6, they're additive (each
captures something the other doesn't) and both should stay.

Est. 7h retrain on Mac mini.

### Experiment B: interaction features

`set2_opener_rate × (current_set==2)` and similar. v5's set-split features
have low *aggregate* gain (set2_opener_rate = 122) but theoretically
high slot-conditional value. LightGBM is supposed to learn these
interactions implicitly but may not be finding them. Explicit feature
engineering is a cheap test.

### Experiment C: explicit anti-predictability feature

`recent_opener_share` — fraction of last 30 set-1 openers that were this
song. Phish avoids repetition; a high value should strongly *down*-rank.
Currently the model relies on `days_since_last_played_anywhere` +
`shows_since_last_set1_opener` to encode this, but both are general-purpose.

### Experiment D: fix `segue_mark_in` zero-gain mystery

Feature has 0 gain. Two candidate causes:
1. Training data has trans_mark=',' on nearly every row (no variance)
2. Bigram already absorbs the segue signal perfectly

Quick triage: count distinct trans_mark values in training rows. If <3
or one dominates at >95%, the feature has near-zero variance and should
either be dropped or re-featurized (e.g., one-hot of trans_mark).

### Experiment E: slot-conditional feature importance

Rather than aggregate `gain`, compute importance separately for
opener slots vs mid-set slots vs encore. Will answer: "does
set2_opener_rate drive set-2-opener slots even though its global gain
is 122?" This is an analysis task, not a model change — just needs a
walk-forward harness that segments by slot type before computing gain.

### Deferred (no new info, deploy-ish)

- **Deploy `nightly-smoke` as cron on Mac mini.** Logs daily
  actual-vs-predicted ranks. Tests infra, accumulates eval data.
  ```bash
  ssh mac-mini 'crontab -l'  # check existing
  # 30 12 * * * ~/.local/bin/uv run --directory ~/phishpicker/api phishpicker nightly-smoke
  ```
- **UI access**: Cloudflare tunnel hostname for NAS `/api` + web so
  the picker is reachable outside loopback.

### Infra tips for re-doing this session's work

If you want to run v5 vs v6 (or any other) side-by-side replay:

1. Ensure NAS SSH is open (ask David if `ssh nas-ssh 'echo ok'` fails
   with "banner exchange timeout").
2. Pull v5 artifacts from NAS:
   ```bash
   ssh nas-ssh 'cat /home/Murphy52/docker/apps/phishpicker/data/model.lgb' > /tmp/v5.lgb
   scp /tmp/v5.lgb mac-mini:/tmp/v5.lgb
   ```
3. Run replay with both:
   ```bash
   ssh mac-mini 'cd ~/phishpicker/api && ~/.local/bin/uv run phishpicker replay \
     --model-a /tmp/v5.lgb --model-b data/model.lgb --show-id 1764702381'
   ```
   (show_id 1764702381 = 2026-04-18 Sphere.)

## Files worth reading for context

- `docs/plans/2026-04-19-signal-research.md` — all domain insights +
  feature roadmap from the 4/18-4/19 David+model session
- `docs/plans/2026-04-17-lightgbm-model.md` — original 17-task plan
- `api/src/phishpicker/train/features.py` — authoritative FEATURE_COLUMNS
- `api/src/phishpicker/train/extended_stats.py` — the fused CTE query
  + feature computation
- `api/src/phishpicker/train/build.py` — the single feature builder both
  training and serving go through
- `api/src/phishpicker/train/albums.py` — album-recency lookup
- `api/src/phishpicker/fixtures/phish_albums.json` — 15 Phish studio
  albums, 184 tracks (179 of which match DB song names)

## Test count

190 tests passing (up from 189 — the v6-revert-revert restored one test).
One file with recent churn: `api/tests/train/test_build_extended_features.py`.

## Open research questions (from signal research doc + v6 outcome)

- **The v5 per-case regression relative to v4 is still unexplained.** It's
  not `days_since_debut`. Candidates: the album-recency batch overall
  (plays_last_6mo, recent_play_acceleration, days_since_last_new_album,
  is_from_latest_album) collectively introduces "recency bias" that
  competes with slot-specific signals. Consider ablating the whole batch.
- Is the `days_since_last_played_anywhere` feature's 22k gain real signal
  or LightGBM memorizing calendar-year patterns? Run ablation.
- Can we make `segue_mark_in` actually contribute? Check if most training
  rows have trans_mark=','. If so, the feature has near-zero variance.
- Does the 9-show Sphere residency generalize to training data? Phish has
  never done a 9-show single-venue run before — model has no in-distribution
  analogue.
- Feature-importance-by-slot-type would be more informative than aggregate
  gain — does `set2_opener_rate` drive set-2-opener slots even if its global
  gain is 122?
