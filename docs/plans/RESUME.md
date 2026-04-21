# Resume Point — 2026-04-20 (late evening update)

✅ **v7 shipped to NAS, serving in production.** Slot-type flags (`is_set2`,
`is_first_in_set`) nearly DOUBLED Top-1 (3.6% → 6.8%) and gained +6.7pp
Top-5 (14.5% → 21.2%) vs v5. Per-case ranks all improved.

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

## Next on the roadmap

- 🛑 **Hold on v8 cleanup** (segue_mark_in/is_cover bug fixes + dead-feature
  drops) until v7 has been observed in production for a bit. We want to
  attribute any shifted behavior cleanly.
- When ready for v8: the findings are in this session's conversation
  summary — two bugs (`segue_mark_in` spaces in lookup, `is_cover`
  inverted + needs Phish-family whitelist per Tom Marshall / TAB
  discussion) and five drop candidates (`historical_gap_mean`,
  `middle_of_set_2_score`, `shows_since_last_played_this_run`,
  `opener_score`, `encore_score`).
- Deferred: nightly-smoke cron on Mac mini (build up a live track
  record of v7's real-world accuracy).

## Commits in this session (most recent first)

| SHA | Summary |
|---|---|
| (uncommitted) | scripts: post_train_eval.py + docs/picking-phish.html + docs/plans/v7-results.md |
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
