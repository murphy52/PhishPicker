# Signal Research — LightGBM Ranker Iteration

> Captures a conversation between David and the model on 2026-04-18 through
> 2026-04-19, triggered by the model missing **Buried Alive** as the
> 4/18 Sphere opener (ranked #45 of 62 scored) while the raw DB signal
> for it was enormous (46% set-1-opener rate).

## 1. Context

**Situation:** Phish is mid-run at the Sphere (9 shows across 3 weekends,
April 2026). v0 prediction model (mixed-artist, pre-feature-engineering)
put Trey-solo songs at the top of the 4/17 and 4/18 opener predictions;
v1 (Phish-only, same feature set) ranked the 4/18 opener at #45. The miss
was entirely feature-coverage, not model capacity: **majority of declared
FeatureRow fields were sitting at sentinel values**.

**Trigger:** David's organic predictions were beating the model by
reasoning about signals the model literally didn't have access to —
Marianne picked Buried Alive correctly because she could see "this song
is 46% set-1-opener every time it's played." The model's only opener
signal was the undifferentiated `opener_score` from the heuristic stats.

---

## 2. Empirical findings from the current DB

### 2.1 No-repeat-within-venue-run is near-absolute

Analysis of all (venue-run, song) pairs where a run = consecutive shows
at the same venue with gap ≤ 2 days:

| Run length | % played once | % 2+ times |
|---|---|---|
| 2 show | 95.7% | 4.3% |
| 3 show | 96.2% | 3.8% |
| 4 show | 97.6% | 2.4% |
| 5 show | 97.3% | 2.7% |
| 6-9 show | 96.9% | 3.1% |
| 10+ show | 97.9% | 2.1% |

**~97% of the time, a song played in a multi-night run is played exactly
once.** The residual is mostly intentional reprises. The current
`played_already_this_run` + hard-rules post-processor correctly encodes
this. For the 9-show Sphere residency this signal becomes powerful by
night 5-6 as the candidate pool shrinks dramatically.

### 2.2 Within-tour repeats follow a bimodal pattern

Tour-level analysis (excluding single-venue residencies):

| Tour length | % played once | % played 2+ | % played 3+ |
|---|---|---|---|
| 3-5 show | 87.9% | 7.2% | 4.9% |
| 6-10 show | 59.4% | 16.9% | 23.7% |
| 11-20 show | 41.0% | 19.4% | 39.6% |
| 20+ show | 33.5% | 17.2% | 49.3% |

Long tours have a **rotation core** (40-50% of the appearing songs are
played 3+ times) AND a **long tail** of one-offs. Short tours are almost
entirely one-offs. `times_this_tour` captures this.

### 2.3 Marquee staples — David's intuition validated

Spotlight on canonical Phish jam vehicles:

| Song | Tours appeared | Multi-play rate | Avg plays/tour |
|---|---|---|---|
| You Enjoy Myself | 108 | 64% | 4.8 |
| Chalk Dust Torture | 117 | 63% | 4.6 |
| Tweezer | 102 | 61% | 4.1 |
| Harry Hood | 115 | 59% | 3.5 |
| Wilson | 106 | 59% | 2.9 |
| Split Open and Melt | 92 | 58% | 3.5 |
| Reba | 90 | 56% | 3.9 |
| Ghost | 89 | 56% | 2.7 |
| Divided Sky | 102 | 50% | 3.5 |

These are the "rotation core" — on any given medium-to-long tour you
expect 3-5 plays of each. They're *distributed* across a 9-show residency
but *concentrated* within single weekends.

### 2.4 Album-recency is a real, large signal

Evolve era (songs debuting 2021-2024):

```
"Evolve":        2021-07:1  2022-05:1  2023-07:4  2025-03:11  2025-11:7
"What's Going   2024-07:3  2025-03:9   2025-11:5
  Through Your
  Mind":
```

New-album songs spike to **4-11 plays per tour** in the 1-2 years
following release, then taper. This is exactly the `is_from_latest_album`
/ `days_since_last_new_album` signal we've been sentinel-stubbing. Big
signal, requires album-metadata ingest to unlock.

---

## 3. Qualitative insights from David (domain expert)

These are hard to encode directly but should shape feature design:

### 3.1 Anti-predictability ("Nash")
> *"The signal I think you're missing is that they don't like to be
> predictable. When I'm thinking about it organically, I'm trying to
> think about what they wouldn't do, within reason."*

The obvious opener for a given night gets downweighted BECAUSE it's
obvious. This is adversarial to our own prediction. Partly captured
implicitly by LambdaRank (it learns residuals over a baseline), but an
explicit feature could help.

### 3.2 Warm-up constraint
> *"They don't come out playing a song that's really hard, because
> they're not warmed up yet."*

Opener candidates skew toward shorter, simpler, higher-energy songs. Not
a feature we can directly measure without phish.in duration data, but
`avg_set_position_when_played` is a decent proxy (songs that play late
average a higher position).

### 3.3 Crowd-pleasing + recency gap
> *"They tend to pick songs that will get the crowd excited, that they
> haven't played in a while, that are going to be good warm-ups."*

Intersection of high frequency AND moderate recency gap. Bustout threshold
features (`bustout_score`, `days_since_last_played_anywhere`) are getting
at this. Could tighten with a composite "sweet spot" score.

### 3.4 Opener rotation
> *"I chose Free [for 4/17] because they haven't opened with it since
> Charleston of last year."*

**Most actionable insight.** Led directly to `shows_since_last_set1_opener`
and `shows_since_last_any_opener_role` (both shipped in batch A-E).

### 3.5 Multi-weekend run distribution (Sphere residency specifically)
> *"The run is broken up into three weekends of three shows each. They
> want to leave really strong songs within each set of three nights, so
> they're not going to play all their big songs in one weekend."*

Strategic marquee-distribution across sub-weekends. Hard to model
directly (need "weekend-of-run" partitioning) but `run_length_total` +
`run_position` together should give LightGBM the context to learn
"when I'm in a long run, space out the big songs."

### 3.6 Categorical distinction: tour vs venue-run
> *"I would not consider it a medium tour. I would consider it a single
> venue run."*

This was worth the empirical check — confirmed the no-repeat rate is
much stricter within a venue-run (97%) than within a cross-venue tour
(41-60%). The features should treat these cases separately.

---

## 4. Features SHIPPED (as of this doc)

v1 → v2 → v3 → (v4 in training) progression of populated fields.

### Batch 1 — Baseline extensions (v2)
- `total_plays_ever`, `plays_last_12mo` — already populated in v0
- `set1_opener_rate`, `set2_opener_rate`, `closer_score`, `encore_rate`
- `times_at_venue`, `venue_debut_affinity`
- `debut_year`, `is_cover`
- `bustout_score`, `days_since_last_played_anywhere`
- `run_position`
- `tour_opener_rate`, `tour_closer_rate`

### Batch 2 — Segue plumbing (v2)
- `segue_mark_in` (trans_mark of prev song piped through training +
  serving + live_songs table)

### Batch 3 — Tour rotation (v3)
- `times_this_tour`
- `shows_since_last_played_this_tour`

### Batch 4 — Domain-informed (v4 — this batch)
- `shows_since_last_set1_opener` — David's Charleston-Free insight
- `shows_since_last_any_opener_role` — broader opener-rotation signal
- `avg_set_position_when_played` — warm-up-fit proxy
- **Relaxed `_find_run_start`** — gap ≤ 2 days + same tour_id (fixes
  multi-weekend residency run-detection)
- **New `find_run_bounds`** — computes both position + total length,
  works for live shows
- `run_length_total`, `frac_run_remaining`

### Infrastructure
- `feature_importance_gain` emitted in `metrics.json` — tells us which
  features actually drive splits post-train
- O(log N) bisect for `shows_since_X` everywhere (replaced O(N)
  per-song SQL counts)
- Fused ~7 separate queries in `compute_extended_stats` into one CTE
  — 3x speedup

---

## 5. Features DEFERRED (next batches)

Ordered by expected signal-to-effort:

### 5.1 Album recency (highest signal, needs ingest)
- `is_from_latest_album` (boolean)
- `days_since_latest_album_release` (for the PERFORMING show, globally
  the same across candidates — useful as a show-level feature)
- `days_since_this_song's_album_release` (for candidates, per-song)

**Blocker:** requires ingesting phish.net's songs-to-albums mapping.
Not on /v5/songs.json directly; may need the separate /albums endpoint.

### 5.2 Jam-vehicle indicator (Phish-specific marquee)
- `marquee_score` = composite of (low frequency) × (high avg_set_position)
  × (segue density in/out)
- `marquee_count_this_run` — running count of marquee songs played in the
  current run. Answers "are we due for a big one?"

### 5.3 "Obvious opener" anti-predictability (the Nash heuristic)
- `recent_opener_share` — fraction of the last 30 set-1 openers that were
  THIS song. If Moma Dance has been opening 40% of recent shows, its
  recent-opener-share is high → "obvious" → model should downweight.

### 5.4 Tour length as a feature (related to batch 4)
- `tour_length_so_far` — number of tour-to-date shows so far (shows
  with same tour_id and show_date ≤ cutoff). Separate from run_length.
- Would help the model distinguish "short tour, one-and-done territory"
  from "long tour, rotation core expected."

### 5.5 Weekend partitioning for multi-weekend residencies
- `weekend_in_residency` — 1st, 2nd, 3rd cluster of the Sphere 9-show run.
  Hard to generalize; may need residency-specific metadata.

### 5.6 Song-metadata stragglers
- `historical_gap_mean` — mean spacing between this song's plays
- `middle_of_set_2_score` — position-rate but for the jam slot (positions
  3-6 in set 2)

### 5.7 Trey-solo / side-project hygiene
Follow-up to the artist_id=1 filter: when Phish covers a Trey-solo song
live, it still gets ingested with artist_id=1 (correctly). But the
`is_cover` flag is currently set by `original_artist IS NOT NULL`, which
doesn't catch Phish members' solo songs as "covers" (original artist is
usually another Phish member). Consider a `is_side_project_song` flag
derivable from songs.original_artist matching {Trey Anastasio, Mike
Gordon, Page McConnell, Jon Fishman}.

---

## 5a. Tuning corrections (post-Oblivion analysis)

The 4/18 set-2 opener analysis (Oblivion missed at #47) surfaced two
calibration issues that a human Phish fan catches instantly but the model
doesn't without tuning:

- **`BUSTOUT_THRESHOLD_SHOWS` was 50, raised to 100.** Real Phish bustouts
  are typically 100-200 shows. Anything under ~40 shows since last play
  is still active rotation. At 5 shows since, a song is "just played" —
  it should *not* get any bustout bonus. The old threshold was
  misclassifying recently-played songs as partial-bustouts.
- **`days_since_last_played_anywhere` is probably the wrong shape for
  Phish.** Their touring is bursty — 80 calendar days might be 0 shows
  (winter hiatus) or 30+ shows (summer tour stretch). Calendar days adds
  noise, not signal. `shows_since_last_played_anywhere` is the real
  rotation signal. Keep the calendar version for now (LightGBM can
  ignore it), but don't trust it as a primary feature and consider
  dropping it if feature-importance post-train shows it's not driving
  splits.

## 6. Open research questions

- **Does the model learn anti-predictability from LambdaRank alone, or
  does it need an explicit feature?** Test by comparing v4 (no explicit
  Nash feature) vs v5 (add `recent_opener_share`).
- **How much does album-recency actually contribute?** Blocked on ingest
  but could estimate an upper bound by manually labeling the last 20 or
  so songs and fitting a v-model with that subset.
- **Is the 9-show Sphere residency covered by any training analogue?**
  If Phish has never done a 9-show single-venue run before (Baker's
  Dozen was 13, NYE MSG 4-5 years had 4), the model has no in-distribution
  examples of `run_length_total=9`. Generalization from 3-5 show runs is
  the best we can hope for.
- **Should hard-rules apply to `shows_since_last_played_this_tour`?** If
  a song was played earlier in the tour at a different venue, it's
  *allowed* to repeat but strongly unlikely. Hard rule vs learned weight?
- **Can we use Marianne-style human predictions as a training signal?**
  She outperformed the model on the Buried Alive call. A handful of
  labeled "human expert" predictions could act as a weak-supervision
  signal — but the data volume is tiny.

---

## 7. Proposed next training runs

Each run = one git push + one Mac mini `phishpicker train run`. Waiter
scripts on the Mac mini can auto-chain them.

| Run | Added features / changes | Blocker |
|---|---|---|
| v4 (current) | Batch 4 (domain-informed) | running |
| v5 | `recent_opener_share` (5.3), `marquee_score` + counter (5.2) | none |
| v6 | Album ingest + `is_from_latest_album` + `days_since_latest_album_release` | phish.net /albums endpoint |
| v7 | `tour_length_so_far` + Trey-solo hygiene | none |
| v8 | Full evaluation: v0 vs v4 vs v5 vs v6 vs v7 with feature-importance deltas, ablation of each batch | none |

## 8. Success metrics to track across versions

- Top-1, Top-5, Top-20 on held-out (20 real Phish shows)
- MRR with 95% bootstrap CI
- Per-slot breakdown (opener / mid-set / encore)
- **Nightly smoke test: real Phish shows as they happen.** Log each
  night's top-10 prediction + actual opener + actual rank of our pick.
  Over the 9-show Sphere residency this alone gives us 9 real-world
  validation points against each model version.

## 9. Housekeeping / deferred items carried over from skeleton plan

- Bootstrap CI is implemented; per-slot breakdown is implemented
- Ship gate with `--override`, staging artifacts on block, implemented
- `feature_importance_gain` emission implemented
- Model-vs-model replay tool — not yet built. Would compare v3/v4/v5 on
  the same live-show slot to show feature-driven ranking deltas
- `/about` page exists but doesn't yet show feature importances — easy
  frontend add once v4 metrics land
