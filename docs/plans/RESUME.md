# Resume Point — 2026-04-17

LightGBM ranker + /about page complete. All 17 plan tasks committed and
tagged v0.2.0-lightgbm.

## Current state

- **Branch:** `main`
- **Tag:** `v0.2.0-lightgbm`
- **API tests:** `cd api && uv run pytest -q` → 143 passing
- **Web tests:** `cd web && npm test` → 53 passing
- **Web build:** `cd web && npm run build` → clean (static `/` + `/about`,
  dynamic `/api/[...path]`)
- **Working tree:** clean

## Tasks complete (all 17)

| Task | Description | Status |
|---|---|---|
| Task 0  | LightGBM + numpy + pandas + sklearn deps + train package skeleton | ✅ |
| Task 1  | FeatureRow dataclass + FEATURE_COLUMNS registry (~30 features) | ✅ |
| Task 2  | Bigram transition probabilities (cutoff-aware, Laplace-smoothed) | ✅ |
| Task 3  | Show-level context (era, DOW, month, tour_position) | ✅ |
| Task 4  | Unified build_feature_rows — training/serving parity | ✅ |
| Task 5  | iter_training_groups — (show, slot) generator | ✅ |
| Task 6  | Stratified hard-negative sampling (freq + uniform) | ✅ |
| Task 7  | LightGBM LambdaRank trainer + 7yr recency weighting | ✅ |
| Task 8  | LightGBMScorer save/load + schema-mismatch guard | ✅ |
| Task 9  | Walk-forward eval with per-fold refit (no leakage) | ✅ |
| Task 10 | Baselines — random, frequency, heuristic + evaluate_scorer | ✅ |
| Task 11 | 95% bootstrap CIs + per-slot metrics breakdown | ✅ |
| Task 12 | Ship-gate — block MRR regression >0.02 | ✅ |
| Task 13 | `phishpicker train run` CLI — atomic model+metrics ship | ✅ |
| Task 14 | LightGBM runtime scorer + heuristic fallback + /about + reload | ✅ |
| Task 15 | /about UI page — headline, baselines, per-slot breakdown | ✅ |
| Task 16 | Era A/B experiment + `train ab-era` subcommand | ✅ |
| Task 17 | E2E validation + RESUME.md + v0.2.0-lightgbm tag | ✅ |

## Carry-forward notes addressed

- **§1 Walk-forward ±2.7pp CI.** Every metric ships with 95% bootstrap CI.
- **§1 Hard-negative stratified sampling.** `iter_training_groups` supports
  `freq_negatives` + `uniform_negatives`.
- **§3 Era A/B gate.** `phishpicker train ab-era` runs the experiment; ship
  era-only unless recency weighting beats by ≥0.01 MRR.
- **§4 Feature leakage.** `walk_forward_eval` refits per fold with
  `cutoff_date = heldout_show_date`. No tour/run aggregates leak.
- **§5 Top-5 as UX metric.** Reported everywhere alongside MRR.
- **§6 Per-slot breakdown.** `WalkForwardResult.by_slot` + `/about` table.

## Still deferred (not in this plan)

- **Jam-length regressor** — separate LightGBM head + UI badges.
- **Bust-out watch** — dedicated endpoint + sidebar.
- **Show archive + replay** — historical browsing with model-vs-truth view.
- **Isotonic probability calibration** — when UI moves to numeric probabilities.
- **Automated in-show ingestion** — phish.net polling / websocket push.
- **SHAP introspection** — per-prediction feature attribution in `/about`.
- **Segue trigrams** — bigrams only for now (trigrams risk overfit at this
  corpus size).

## Pending deployment steps (require NAS + Mac mini)

1. `ssh mac-mini && cd ~/phishpicker/api && uv run phishpicker train run`
   (expect <10 min on ~1800 shows × 50 negatives).
2. `bin/ship.sh` to scp + atomic-rename artifact + DB to NAS.
3. Hit `POST /internal/reload` via admin token.
4. Verify `/about` renders through Cloudflare tunnel.
5. Measure `/predict/{id}` p50 < 500ms on NAS hardware.

## Next plans

Write separate plans for:

1. **Jam-length model** — LightGBM regressor on phish.in durations.
2. **Bust-out watch** — low-probability/high-gap sidebar.
3. **Show archive + replay** — `/shows`, `/shows/[id]`.
4. **Automated in-show ingestion** — phish.net polling + websocket push.
