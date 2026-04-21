# Residency / Run Awareness — Plan

**Status**: proposed (not started)
**Opened**: 2026-04-20
**Motivating incident**: v7 preview for Sphere Night 4 (2026-04-23) picked
`Also Sprach Zarathustra` even though it was played on Night 1 (2026-04-16),
and assumed a 1-encore structure in the feature landscape. Both trace back
to run-detection being unaware the full Sphere residency is a single
9-show run.

## Background

Phish behavior we want to capture:

1. **No-repeat within a run.** Fan norm; model already has
   `played_already_this_run` to encode this, but only when run detection
   correctly spans the whole residency.
2. **"Don't exhaust favorites."** In a 9-show run, Phish spreads
   signature songs across the run rather than blowing them on Night 1.
   Each additional night is another chance for Hood, YEM, Tweezer,
   Mike's→Hydrogen→Weekapaug, Fluffhead, Divided Sky, etc. Model
   currently has no way to represent "5 more nights to fit this in."
3. **Residencies behave differently from tour stops.** Baker's Dozen-style
   runs have more themed sets, more deliberate rotation, more bustouts.

### Current run-detection flaw (v7)

`model/stats.py::_find_run_start` / `_find_run_end` walk adjacent show
dates with `_RUN_MAX_GAP_DAYS = 2` (one off-night tolerated). The Sphere
residency has a 4-day mid-residency gap (4/18 → 4/23), so v7 sees two
3-show runs (4/16-4/18 and 4/23-4/25) plus a final 3-show run (4/30-5/2)
instead of one 9-show run.

**Concrete miss**: on 2026-04-23 Night 4, v7 ranked `Also Sprach
Zarathustra` in the top-5 of the Set 2 closer slot even though the song
had been played on 2026-04-16. The feature `played_already_this_run`
returned 0 for Night 4 because Night 1 isn't "in this run" under the
2-day-gap rule.

## Q1 — How we know the full run at Night 1

Phish.net's `/shows.json` returns **future-dated shows** with `show_date`,
`venue_id`, and `tour_id` populated (setlist blank). Ingest already
writes these to the `shows` table. Verified: all 9 Sphere dates are
already present in the training DB.

→ **The data is already there.** The fix is purely in how we define a
"run."

## Proposed fix — walk until venue changes

Current gap-based walk is brittle (tunable threshold, fails on long
residency gaps). Replace with a simpler rule:

> Walk chronologically through scheduled shows; a run is an unbroken
> sequence at the same venue.

```python
def find_run_bounds(conn, venue_id, show_date):
    if venue_id is None:
        return (show_date, show_date, 1, 1)

    # Walk backward through scheduled shows until venue changes.
    start = show_date
    cur = show_date
    while True:
        prev = conn.execute(
            "SELECT show_date, venue_id FROM shows "
            "WHERE show_date < ? ORDER BY show_date DESC LIMIT 1",
            (cur,),
        ).fetchone()
        if not prev or prev["venue_id"] != venue_id:
            break
        start = prev["show_date"]
        cur = prev["show_date"]

    # Walk forward through scheduled shows until venue changes.
    end = show_date
    cur = show_date
    while True:
        nxt = conn.execute(
            "SELECT show_date, venue_id FROM shows "
            "WHERE show_date > ? ORDER BY show_date ASC LIMIT 1",
            (cur,),
        ).fetchone()
        if not nxt or nxt["venue_id"] != venue_id:
            break
        end = nxt["show_date"]
        cur = nxt["show_date"]

    shows = [
        r[0]
        for r in conn.execute(
            "SELECT show_date FROM shows "
            "WHERE venue_id = ? AND show_date BETWEEN ? AND ? ORDER BY show_date",
            (venue_id, start, end),
        ).fetchall()
    ]
    if show_date not in shows:
        shows.append(show_date)
        shows.sort()
    run_position = shows.index(show_date) + 1
    return (start, end, run_position, len(shows))
```

**Properties:**
- Handles any gap length without a threshold.
- No-op for single-night stops.
- Correctly identifies 9-show Sphere as one run (assuming no intervening
  non-Sphere show is scheduled, which phish.net confirms).

### Edge cases to think about

1. **Unrelated future run at same venue, not yet ingested.** E.g.,
   Phish plays Hampton 3/15-17 and a second Hampton run is scheduled
   10/10-12 but no intermediate shows are ingested. Walk-forward from
   3/15 would include 10/10-12 in the same "run." Mitigation:
   **intersect with `tour_id`** — shows in different tours are never
   the same run even at the same venue. `find_run_bounds` already
   accepts `tour_id`; always pass it when available.
2. **Future shows not yet announced.** e.g., at Night 1 of 9, only
   nights 1-9 are ingested but a future 10-night run at the same venue
   isn't public yet. Walk-forward is correct because the 10-night run
   doesn't exist in the DB.
3. **Ingest staleness.** If we haven't pulled from phish.net since
   dates were added, walk-forward gives an under-count. Mitigation:
   re-ingest before major predictions; also mostly self-correcting
   because tours announce well in advance.
4. **Run position 1 when Night 1 isn't the scheduled first.** Walk
   backward handles this correctly: if we're predicting for what turns
   out to be night 2 (because a surprise show was added night-of),
   we see the prior date and place ourselves at position 2.

**Decision**: go with walk-until-venue-changes, AND pass `tour_id` as a
safety intersection. This is functionally equivalent to "same venue +
same tour" chronologically-contiguous shows.

## Q2 — Run-aware feature family

With correct run boundaries, these new features become computable and
meaningful:

### Feature 1: `run_length_scheduled` (int)
Total shows in the run as scheduled. Known at Night 1. Captures "this
is a 2-night stop" vs "this is a 9-night residency." Phish's rotation
discipline differs by run length.

### Feature 2: `nights_remaining_in_run` (int)
`run_length - run_position`. Signals how many future chances a song
still has. At Night 4 of 9, remaining=5; at Night 9 of 9, remaining=0.
Songs that haven't been played yet get more pressure to appear as
remaining → 0.

### Feature 3: `plays_this_run_count` (int, replaces binary)
Current `played_already_this_run` is 0/1. Replace with the actual
count of plays this run. Distinguishes:
- not yet played (0) → neutral
- played once (1) → strong negative (no-repeat norm)
- played 2+ times (2+) → very strong negative (unprecedented but
  technically possible, e.g., the "Tweezer reprise" convention where
  Tweezer proper shows once and TR shows once)

The binary feature already encodes (1) vs (0); this refinement lets
the model learn that 2 plays in one run is a harder rule than 1 play.

### Feature 4: `run_saturation_pressure` (float) — **the key one**
Per-song, per-slot estimate of "is this song due to appear?"

```
expected_plays_so_far = historical_per_show_rate × shows_played_so_far
pressure = expected_plays_so_far - plays_this_run
```

- `historical_per_show_rate` = plays in last ~5 years / shows in last
  ~5 years (i.e., how often this song normally shows up per show).
  Reuse `plays_last_12mo` / show count denominator we already compute.
- Positive pressure → "overdue, bump up." Negative → "already used,
  bump down."
- For songs with very low rates (bustouts), pressure is tiny and
  doesn't meaningfully move the score — which is correct, we don't
  expect Forbin's every 9 nights.

Conceptually this is a residency-scoped analog of
`days_since_last_played_anywhere`. That feature answers "is this song
overdue in absolute time"; this one answers "is this song overdue
*within this residency*."

### Feature 5: `is_residency` (bool or int)
`1 if run_length_scheduled >= 4 else 0`. Threshold arguable (4 is
NYE-run territory). Lets the model learn different weights for
residency vs tour stops. Could also be continuous (sqrt-scaled
run_length) to avoid a hard cliff.

### What we DON'T need
- Per-song "saved for later" heuristic with manual priors. Let the
  model learn from historical Baker's Dozen / NYE patterns.
- Fan-favorite flag. The model already captures "this song is heavy
  rotation" via `plays_last_12mo`. Saturation pressure composes with
  it.

## Training-data concerns

Runs of length ≥ 6 in training data are rare:
- Baker's Dozen 2017 (13 nights, MSG)
- Sphere 2024 (4 nights)
- NYE 4-show runs most years
- Most other residencies: 3 nights or fewer

n is small for 9-night behavior specifically. Model will have to
generalize from 3-4 night runs (which have weaker but directionally
similar rotation discipline). Risk: `is_residency` and
`run_saturation_pressure` could be noisy at run_length=9 until more
multi-night runs accrue. Acceptable — the Sphere dataset is live-
growing and each run adds 9+ training slots per feature.

Specific ablations worth running post-implementation:
- Compare holdout metrics on residency shows (run_length ≥ 4) vs tour
  stops separately. Does v10 improve residency predictions more than
  tour-stop predictions?
- Hold out Baker's Dozen entirely and see if v10 can reproduce its
  "no signature-repeat across 13 nights" behavior.

## Implementation order

1. **Fix `find_run_bounds`** — walk-until-venue-change, still accepting
   `tour_id`. Keep signature compatible. Ensure training caller passes
   `tour_id` too.
   - Tests: Sphere case (9-show run across 4-day gap), Baker's Dozen
     (13-show run), tour-stop (1-show), consecutive 2-night stop.
   - Expected: no retrain needed to see v7 stop picking 2001 again —
     `played_already_this_run` now correctly triggers.
2. **Replace binary `played_already_this_run` with integer
   `plays_this_run_count`** in the feature schema. Keep 0/1 semantics
   available as a derived check.
3. **Add `run_length_scheduled`, `nights_remaining_in_run`,
   `is_residency`** to FeatureRow + build.py.
4. **Add `run_saturation_pressure`** — needs per-song
   historical-rate lookup. Consider caching in a small map keyed by
   (song_id, as_of_show_date) to avoid re-querying.
5. **Retrain** as v10. Use `--cutoff 2026-04-18` for apples-to-apples
   with v7.
6. **Replay 2026-04-18 and 2026-04-23** to validate. Specifically:
   does v10 rank 2001 outside top-20 on Night 4? Does it promote
   still-unplayed favorites (Hood, YEM, Fluffhead, Divided Sky)
   on later nights?

Each step ships independently. Step 1 alone fixes the Night 4
preview's 2001 issue; steps 3-4 are the feature-engineering lift.

## Acceptance criteria

- After step 1: `played_already_this_run` returns 1 for any song that
  appeared on any prior night of a 9-show Sphere residency, regardless
  of mid-residency gaps. Verify via a unit test on the 2026-04-16-to-
  2026-04-23 case.
- After v10 retrain: holdout Top-5 on shows in runs of length ≥ 4
  improves by at least 2pp over v7, or we explain why not.
- Qualitative: Night 4 preview no longer picks a Night 1 song, and
  preference ordering shifts plausibly toward not-yet-played favorites
  as run_position advances.

## Open questions

1. Should `run_saturation_pressure` use a 1-year historical rate or a
   tour-specific rate? (Phish rotates songs in/out of a tour's "book";
   a tour-rate would weight more heavily.)
2. Is `is_residency` redundant with `run_length_scheduled`, or does
   the threshold encode something the continuous feature can't? LightGBM
   can learn thresholds from the continuous version — probably redundant.
3. When a run crosses a year boundary (NYE runs 12/28-1/1), does the
   walk still work cleanly? Yes — show_date comparisons are
   lexicographic on ISO dates, so 2025-12-31 < 2026-01-01.
4. For previews (live shows) on run days we haven't ingested yet: the
   walk-forward sees future shows, which is correct. But when the
   current live_show's date itself isn't in `shows`, we need to inject
   it (current code already does this in `find_run_bounds`).

## Related / superseded

- Supersedes v7's `_RUN_MAX_GAP_DAYS=2` tunable.
- Complements `v7-residual-analysis.md` (which proposed
  `slots_into_current_set`). These are independent features; both can
  ship in v10 if scheduled in the same retrain.
