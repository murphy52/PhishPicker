# Filter songs played earlier in the run

## Goal

During a Phish residency / multi-night run, hard-filter from candidate predictions any song that was played in a prior show in the same run. Phish almost never repeats songs night-to-night during a run; the model should reflect that as a strict rule, not a soft penalty.

Triggered by an observed bug on 2026-04-24: `Stash` was predicted #2 for the Sphere set 1 opener even though Phish played it in Set 1 the night before (2026-04-23, also Sphere). The model has gap awareness but no run-aware exclusion.

## Run definition

A run is a chronologically-adjacent block of same-venue shows within the same tour. Already implemented in `api/src/phishpicker/model/stats.py:_find_run_start` / `_find_run_end` — those walk shows ordered by date, stopping at venue changes, optionally constrained to a `tour_id`.

For this filter, the run walk is **tour-constrained** (option A from brainstorming). Tour resolution at preview time uses the `tours` table by `show_date`. Without the tour constraint, two same-venue residencies separated by years (Sphere 2024 vs Sphere 2026) could glue together; with it, they stay distinct.

## Data flow

Inside `build_preview` (`api/src/phishpicker/live_preview.py`), once per `/preview` call:

1. Resolve `tour_id` from `tours` by the live show's `show_date`. If none found, treat the show as not-in-run; the filter becomes a no-op.
2. Walk run bounds via `_find_run_start` / `_find_run_end` constrained to `(venue_id, tour_id)`.
3. Query `setlist_songs` joined to `shows` for songs in shows where `venue_id = ?`, `tour_id = ?`, `run_start ≤ show_date < live_show.show_date`. Build `played_in_run: set[int]`.
4. Pass `played_in_run` through every prediction call — predicted slots and `_compute_hit_rank` for entered slots.

Cost: one extra read query at `/preview` boot, reused across all 18 slots. No per-slot overhead.

## Function changes

- `model/rules.py`: extend `apply_post_rules(scored, played_tonight, played_in_run: set[int] | None = None)` to drop candidates whose `song_id` is in either set. Default keeps training callers unchanged.
- `predict.py:predict_next_stateless`: new optional kwarg `played_in_run`, passes through to `apply_post_rules`.
- `live_preview.py`: new helper `_played_in_run(read_conn, show_date, venue_id) -> set[int]` that resolves tour_id internally and returns the set (empty when no tour or no prior run-mate shows). `build_preview` computes it once at the top of the function, passes it to every `predict_next_stateless` call (predicted-slot path) and `_compute_hit_rank` call (entered-slot path).

No schema changes. No new migrations.

## Why the filter applies to `_compute_hit_rank`

The hit-rank indicator (issue #6, just shipped) reports the entered song's rank in the model's retroactive top-10. If the predicted slots' candidate pool excludes run-mate songs, the entered slot's pool must too — otherwise the indicator would compute a rank against a different model than the user actually saw. If a song that was played earlier in the run is repeated tonight (rare), the entered-slot rank becomes `null` (em-dash). Acceptable — the model legitimately said "won't happen" and was wrong.

## Tests

**Unit (`api/tests/test_rules.py` or wherever the rules test lives):**
- `apply_post_rules` excludes a song that is in `played_in_run` but not in `played_tonight`.
- `apply_post_rules` excludes a song that is in both sets (idempotent).
- `apply_post_rules` with `played_in_run=None` matches today's behavior.

**Integration (`api/tests/test_live_preview.py`):**
- Seed a live show + a prior run-mate canonical show whose setlist contains a known song. GET `/preview`. Assert that song does not appear in any predicted slot's `top_k`.
- Seed a live show that is night 1 of a run (no prior shows in the run). Assert filter is empty and predictions match the prior-test baseline.
- Seed a live show whose date doesn't fall within any tour. Assert filter is empty and predictions are unchanged.

## Out of scope

- Soft penalty / weighting variants. The user specified a hard rule.
- Song-family rules (e.g., `Tweezer` and `Tweezer Reprise` treated as separate songs).
- Cross-tour residencies — handled by the tour constraint.
- Live show schema additions — tour resolution happens at preview time.
- Stale ingest concerns: if a prior night's setlist hasn't been scraped yet, those songs aren't filtered. Data-freshness is a separate problem.
