# Resume Point — 2026-04-20

Deep into signal-iteration phase. v5 shipped to NAS; v6 training finishing.

## TL;DR for next session

- **Mac mini** is running v6 training (pid 87506). Last check: 6h 51min
  elapsed, on the final walk-forward fold (2026-04-17 cutoff), ~3-5 min
  from writing `~/phishpicker/api/data/metrics.json`.
- **NAS** currently serves v5 at `http://127.0.0.1:3400` (loopback only).
- **Key pending action**: once v6 finishes, ship its artifacts to NAS and
  re-run the Buried Alive / Oblivion replay to see if dropping
  `days_since_debut` restored the per-case ranks (see `replay tests`
  section below).

## Commits in this session (most recent first)

| SHA | Summary |
|---|---|
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
| v6 (training) | −days_since_debut (v5 redundancy fix) | ? | ? | ? | hypothesis test |

Headline metrics are bounded by n=358 holdout slots (CI on Top-1 ≈ ±2pp).

### Per-case validation (4/18 Sphere opener + set-2 opener)

| Slot | Actual | v0 | v4 | v5 | v6 |
|---|---|---|---|---|---|
| 4/18 opener | Buried Alive | #45 | #8 | #11 | **pending** |
| 4/18 set-2 opener | Oblivion | #47 | #3 | #6 | **pending** |

v6 hypothesis: dropping `days_since_debut` should recover Buried Alive/
Oblivion ranks without losing v5's +0.8pp Top-5 lift.

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
    39395 setlist rows, 983 songs, latest ingested 2026-04-17)
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

### Step 1: Pick up v6

```bash
ssh mac-mini 'tail -10 /tmp/phishpicker-train-v6.log; ls -la ~/phishpicker/api/data/metrics.json'
```

If v6 still running, wait. If finished, proceed.

### Step 2: Ship v6 to NAS

```bash
mkdir -p /tmp/v6
scp mac-mini:/Users/admin/phishpicker/api/data/{model.lgb,model.meta.json,metrics.json} /tmp/v6/
cat /tmp/v6/model.lgb         | ssh Murphy52@storage.local 'cat > /home/Murphy52/docker/apps/phishpicker/data/model.lgb.new && mv /home/Murphy52/docker/apps/phishpicker/data/model.lgb.new /home/Murphy52/docker/apps/phishpicker/data/model.lgb'
cat /tmp/v6/model.meta.json   | ssh Murphy52@storage.local 'cat > /home/Murphy52/docker/apps/phishpicker/data/model.meta.json'
cat /tmp/v6/metrics.json      | ssh Murphy52@storage.local 'cat > /home/Murphy52/docker/apps/phishpicker/data/metrics.json'
ssh Murphy52@storage.local 'cd /home/Murphy52/docker/apps/phishpicker && docker compose restart api'
```

NOTE: NAS SSH window may be closed. If so, ask David to re-enable.

### Step 3: Replay 4/18 on v6

Use the existing replay script at `/tmp/v4-replay.py` (same flow works for v6):

```bash
cat /tmp/v4-replay.py | ssh Murphy52@storage.local 'python3'
```

Look for where Buried Alive and Oblivion rank. Compare to v4 (Buried #8,
Oblivion #3) and v5 (Buried #11, Oblivion #6).

### Step 4: If v6 validates the redundancy hypothesis

Update `docs/plans/2026-04-19-signal-research.md` with the v6 numbers.
Tag it as a completed experiment.

Then consider next batch:
- Explicit anti-predictability feature (`recent_opener_share` — fraction
  of last 30 set-1 openers that were this song)
- Fix `segue_mark_in` zero-gain mystery (check if trans_mark has variance
  in training rows)
- Interaction features (e.g., `set2_opener_rate × (current_set==2)`)
- Deploy `nightly-smoke` as a cron on Mac mini
- UI access: Cloudflare tunnel hostname for NAS `/api` + web

### Step 5: Nightly smoke cron (deferred)

When ready:
```bash
ssh mac-mini 'crontab -l' # check existing
# add line like:
# 30 12 * * * ~/.local/bin/uv run --directory ~/phishpicker/api phishpicker nightly-smoke
```

Idempotent by show_id; skips already-recorded dates.

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

189 tests passing. One file with recent churn:
`api/tests/train/test_build_extended_features.py`.

## Open research questions (from signal research doc, still valid)

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
