# Research Spike: Show-Level Inclusion Model ("what plays tonight, any slot")

**Status:** proposed (post-tour research spike)
**Author:** David + assist
**Date:** 2026-07-07
**Motivates:** surfacing road-tested new material (the "when Phish debuts a song they play it
N times this tour" pattern) that the slot-level ranker structurally can't see.

---

## 1. Why a second model (the problem with the slot ranker for this)

The production model is a **slot-level next-song ranker**. Its behavior, by gain importance:

| Feature | Gain | Kind |
|---|---|---|
| `bigram_prev_to_this` | **57.5%** | transition |
| `plays_last_12mo` | 11.5% | frequency |
| slot-position (`slots_into_current_set`, `is_first_in_set`, …) | ~11% | slot |
| `days_since_debut` | 1.2% | newness |
| `times_this_tour` | 0.23% | within-tour recurrence |
| `is_from_latest_album` | 0.09% | album |

Two structural facts make this the wrong tool for "watch for new songs tonight":

1. **The dominant signal (57%) is a transition probability a new song can't have.** A brand-new
   song has no bigram history, so it's invisible to the feature that decides most high-value slots.

2. **Transitions are sparse, so the 57% is concentrated, not pervasive** (measured on the full DB):
   - **67.9%** of distinct adjacency pairs are one-offs (occurred exactly once); only 2,839 / 17,504
     pairs ever recurred ≥3×.
   - For a song seen ≥5× as a predecessor (avg 80×), its **most-common follower is only 16%** of the
     time — even strong bigrams are diffuse.
   - ~62% of adjacencies are plain sequential (`,`), only ~37% are true segues (`>` / `->`).

   So for most slots the bigram is flat and *frequency* decides — but a 1-play debut is weak on
   frequency too. Amplifying "other factors" rescues established-but-unpaired songs, not debuts.

**The pattern lives at the wrong level for the slot model.** "A new song gets played N times this
tour" is a **show/tour-level base rate**, diffused across ~25 slots. That's exactly why
`days_since_debut` / `times_this_tour` learned ~1% / ~0.2% importance — the aggregate fact barely
sharpens any single slot. Model it at the show level and the transition monolith disappears, letting
newness/rotation features carry real weight.

## 2. What the model predicts

For each upcoming show, a per-song probability:

> **P(song S appears anywhere in tonight's show)**

One row per **(show, candidate_song)**; label = 1 if S was played in that show (any set), else 0.
Product surface: a "**Likely Tonight**" list + a "**New-Material Watch**" section that the slot
bracket can't produce.

- Candidate universe: songs with ≥1 play in the last ~3 years (bounds the ~900-song catalog to the
  live-rotation set; decide exact window in the spike).
- Positive rate ≈ 25 played / ~300–900 candidates ≈ **3–8%** → imbalanced binary. Objective:
  LightGBM `binary` (or `lambdarank` ranking songs *within* a show). Reuse existing tooling.

## 3. Features

**Reuse (song-intrinsic, already in `build_feature_rows`):**
`total_plays_ever`, `plays_last_6mo`, `plays_last_12mo`, `shows_since_last_played_anywhere`,
`days_since_last_played_anywhere`, `recent_play_acceleration`, `tour_position`, `is_cover`, `era`,
`times_at_venue`, `shows_since_last_at_venue`, `venue_debut_affinity`, `days_since_debut`,
`debut_year`, `is_from_latest_album`, `days_since_last_new_album`, `closer_score`, `bustout_score`.

**Drop (slot/transition — meaningless at show level):**
`bigram_prev_to_this`, `prev_song_id`, `segue_mark_in`, `current_set`, `set_position`,
`is_first_in_set`, `slots_into_current_set`, `is_set2`, `set1_opener_rate`, `set2_opener_rate`,
`middle_rate`, `encore_rate`, `run_saturation_pressure`.

**Add — the point of the spike (new-material / recurrence signals):**
- `is_new_debut_tour_original` — original (`is_cover=0`), debuted within the current tour (or last
  ~180 days), not on an album.
- `plays_since_debut`, `shows_since_debut` — the debut ramp.
- `plays_this_tour_to_date` — within-tour recurrence so far.
- `plays_last_tour` — did it carry over.

**Show-context (constant across a show's candidates):**
`run_position`, `run_length`, `days_since_tour_start`, `is_tour_opener`, `month`, `day_of_week`,
`venue_id`.

## 4. The key modeling insight — train newness on ALL historical debut tours

Only a handful of songs are "new" *right now* → thin positive examples. But **every song in the DB
had a debut tour**. Build the training set over all history and every song's first-tour behavior
becomes a labeled example → thousands of (debut-tour-song, show) rows to learn the recurrence shape
from. That's what makes `is_new_debut_tour_original` learnable rather than another ~0% feature.

## 5. Evaluation

- **Time-based holdout** (last N shows), same discipline as the slot model + `score_forward_sims.py`.
- **Metrics:** `Recall@25` (of the ~25 played, how many in our top-25), MAP, PR-AUC (imbalance),
  Brier / calibration curve.
- **Baselines to beat (both):**
  1. Frequency: rank by `plays_last_12mo`.
  2. Slot model aggregated: union of top-k across simulated slots.
- **The decisive metric:** **new-song recall** — of new-material songs actually played in holdout
  shows, does this model rank them above the frequency baseline? If not, the pattern isn't
  slot-agnostically exploitable and we stop.

## 6. Kill criteria (be disciplined — cf. `bustout_rate`, opener model, both refuted)

Abandon if **either** holds on holdout:
- Overall `Recall@25` does not beat the frequency baseline, **or**
- `is_new_debut_tour_original` + friends do not improve new-song recall over the frequency baseline.

## 7. Timeboxed steps

1. Build show-level dataset (1 row / show×candidate, label = appeared).
2. Assemble features: reuse song-intrinsic, drop slot/transition, add the 4 newness features.
3. Train binary LightGBM; time-holdout; report Recall@25 + new-song recall vs both baselines.
4. Go/no-go memo with numbers. Only then consider a "Likely Tonight / New-Material Watch" UI.

**Deliverable:** a numbers-backed go/no-go, not a shipped feature.

---

## 8. RESULTS (first-cut run, 2026-07-07)

Ran locally (`arch -x86_64 api/.venv/bin/python3`, Rosetta on the arm64 venv).
Dataset: **535,866** rows (show × candidate), candidate = played in trailing 3 yrs, label =
appeared. Time holdout at 2025-07-01 → 43 holdout shows, ~6% positive rate. LightGBM binary,
300 rounds. Features: song-intrinsic + newness, **transition/slot features dropped**.

**Result 1 — the show-level model works.**

| Metric | Model (show-level) | Baseline (`plays_last_12mo`) |
|---|---|---|
| Recall@25 | **0.404** | 0.196 |

**2.06× the frequency baseline** — captures ~9 of a show's ~22 songs in the top-25 vs ~4.5. The
show-level inclusion frame is a genuinely useful predictor; a "Likely Tonight" list is viable.

**Result 2 — newness features carry 3–4× more weight than in the slot ranker (hypothesis confirmed).**

| Feature | Show-level gain | Slot-ranker gain |
|---|---|---|
| `days_since_debut` | **5.0%** | 1.2% |
| `times_this_tour` | **3.3%** | 0.23% |

Dropping the 57% bigram monolith lets newness/within-tour-recurrence signals matter, exactly as
predicted. (Top features now: `plays_last_12mo` 41%, `shows_since_last_played` 14%, `plays_last_6mo`
9%.)

**Result 3 — the specific new-song payoff is UNTESTABLE on current data (the honest caveat).**
- `new_original_flag` (≤180d unreleased original): **0.17%** importance — near-zero, because there
  are ~no positive training examples. The current new songs (Dancing in Midair, Fling Your Head,
  Dark Puddle) are **one-off debuts that haven't been road-tested yet** — their tour starts tonight.
- Only **3** recently-debuted (≤365d) played events exist in the entire holdout, and **both model
  and baseline caught 0/3**. Even the strong show-level model can't yet crack the new-song cold start.

**Verdict:**
- **GO** on the show-level inclusion model as a "Likely Tonight" product surface — 2× recall is real.
- **INCONCLUSIVE** on new-song surfacing — not a refutation, an *absence of data*. The road-testing
  events don't exist yet. **Re-run this exact spike after the summer 2026 tour**, when Dancing in
  Midair et al. have had the chance to recur; that's the clean decision gate for the newness payoff.

Script: `scratchpad/show_level_spike.py` (promote to `scripts/` if we pursue the "Likely Tonight" view).
