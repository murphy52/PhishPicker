# Resume Point — 2026-04-20 (late-night session-3 update)

## This session's work (2026-04-20 evening)

Triggered by a full-show preview for **Sphere Night 4 (Thursday 2026-04-23)**
using the live v7 model. Two problems surfaced:

1. **v7 picked `Also Sprach Zarathustra`** even though it played Night 1
   (2026-04-16). Root cause: `_find_run_start`/`_find_run_end` used a
   2-day gap rule. The 4-day mid-residency gap (4/18 → 4/23) split the
   9-show run into two 3-show runs.
2. **No "save favorites for later" concept**. On a 9-night residency,
   Phish spreads signature songs across the run rather than blowing them
   early. The model has no feature encoding this.

### Shipped this session

| Commit | Summary |
|---|---|
| `b09e76a` | docs: v10 plan (`2026-04-20-residency-run-awareness.md`) |
| `d31ff84` | **fix(stats): walk-until-venue-changes run detection.** |
| `ec023a3` | **feat(train): plays_this_run_count replaces binary.** |

All pushed to origin/main.

`d31ff84`:
- `_find_run_start`/`_find_run_end` walk chronologically until venue
  changes (intersected with `tour_id` when available). No threshold.
- Handles arbitrary-length gaps — the Sphere run (and any residency
  with mid-run off-blocks) is now correctly detected as one run.
- **No retrain needed for this fix.** It changes values the v7 model
  already consumes (`played_already_this_run`, `run_length_total`,
  `run_position`, `frac_run_remaining`). Values now more accurate;
  `played_already_this_run` firing correctly on Night 4+ is pure upside.
- Tests: 2 new (Sphere gap, intermediate-venue break) + 1 renamed
  old test (3-day-gap → supersedes), 204 tests pass.

`ec023a3`:
- Replaces binary `played_already_this_run` on FeatureRow with integer
  `plays_this_run_count` (0, 1, 2, ...). `SongStats` keeps the binary
  as a derived bool for the heuristic scorer; LightGBM gets the count.
- **This is a schema-breaking change for LightGBM.** The
  `assert_compatible_with` guard will refuse to load a v7 model against
  v10 code. A retrain is required before deploying v10 code.
- Tests: 2 new at stats layer, 1 new at feature-row layer, 207 tests pass.

### Deploy state after this session

- **NAS still serves v7** (unchanged — nothing deployed tonight).
- **v10 code on origin/main**; Mac mini not pulled yet.
- **Mac mini has untracked `scripts/post_train_eval.py`** blocking
  `git pull`. Needs resolution before a v10 retrain:
  ```bash
  ssh mac-mini 'cd ~/phishpicker && git status'
  # then either `git add` + commit the helper, or delete it if superseded
  ```
- **scp to Mac mini was permission-denied** in this session by the
  deploy-safety rule — code must move via git. Fine; push is on origin.

## What's next

### Immediate decision required: `run_saturation_pressure`

Third proposed v10 feature. Formula:
`(plays_last_12mo / shows_last_12mo) × (run_position − 1) − plays_this_run_count`.
Positive = song overdue this run; negative = already used.

**Arguments against**: LightGBM trees can learn this interaction from
existing features (`plays_last_12mo`, `plays_this_run_count`, `run_position`)
via sequential splits. Explicit engineering adds one SQL query per show
and encodes a uniform-rate assumption that may not match Phish's actual
dynamic (day-of-week patterns, themed nights, etc.).

**Arguments for**: direct axis > composite splits on small training data
for long residencies. Cheap to add; easy to drop in v11 if feature
importance stays low.

**David was deciding when session paused.** Two paths:
- **Path A (add it)**: one more TDD cycle, then retrain v10.
- **Path B (skip it)**: retrain v10 now with just run-detection fix +
  `plays_this_run_count`. Add `run_saturation_pressure` in v11 if
  Night 4-9 residency predictions still show "didn't save favorites"
  misses.

### Then: retrain v10 on Mac mini

Once Mac mini `git pull` is unblocked:
```bash
ssh mac-mini 'cd ~/phishpicker/api && ~/.local/bin/uv run phishpicker train run --cutoff 2026-04-19'
```
(`2026-04-19` = day after Night 3 Sphere; keeps the residency itself
out of training for a clean Night-4 replay.)

Expect 3–4h based on v7 timing. Artifacts land at
`~/phishpicker/api/data/{model.lgb, metrics.json, model.meta.json}`.

### Then: deploy v10

`bash scripts/deploy_to_nas.sh` — schema-mismatch check will pass now
that code+model are both v10. NAS SSH window must be open.

### Then: validation on live shows

| Date | Event |
|---|---|
| Thu 2026-04-23 | Night 4 — first real-world v10 test |
| Fri 2026-04-24 | Night 5 |
| Sat 2026-04-25 | Night 6 |
| Thu 2026-04-30 | Night 7 |
| Fri 2026-05-01 | Night 8 |
| Sat 2026-05-02 | Night 9 |

After each show, run `phishpicker nightly-smoke` to log ranks. Key
metric: does `plays_this_run_count` correctly down-weight songs played
on prior nights? (Should; it's strictly more info than the binary.)

## Session-3 preview run artifacts

The Night 4 preview logic is in `/tmp/preview_0423.py` on this local
machine (not committed). Uses greedy top-1 per slot; applies a
post-filter for residency repeats (which is now redundant with the
run-detection fix). Re-run after v10 ships to confirm `Also Sprach`
and other Night 1-3 songs drop organically.

Phish DB show_ids used:
- Night 1: 1764702178 (4/16)
- Night 2: 1764702334 (4/17)
- Night 3: 1764702381 (4/18)
- Night 4: 1764702416 (4/23) — not yet ingested with setlist

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
