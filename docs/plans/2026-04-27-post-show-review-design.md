# Post-show review window — design

**Issue:** [#5 — Post-show review window for /upcoming and the PWA](https://github.com/murphy52/PhishPicker/issues/5)
**Status:** approved 2026-04-27

## Goal

After a show ends, give the user a way to look back at the actual setlist
side-by-side with where the model's predictions landed. Restricted MVP: just
the most-recent past show (N-1), accessed via a footer link from the picker.
Bustout/LTP highlights and a browseable history are deferred.

## User flow

- Picker page (`/`) is unchanged.
- Footer gains a `last show` link (right column, second row, alongside
  `about`). Hidden when no past show is available.
- Clicking the link opens `/last-show` — the review for the most-recent
  completed show.
- The review page header mirrors `ShowHeader` (venue, date, residency
  Run badge if applicable). Body is a scrollable list of slots grouped
  by `SET 1` / `SET 2` / `ENCORE`, matching the picker's visual rhythm.
- Each slot row: actual song name + a small color-coded rank pill on the
  right.

```
SET 1
  1   Timber (Jerry the Mule)              [#7  ]
  2   The Moma Dance                       [#1  ]
  3   The Final Hurrah                     [#23 ]
  ...
```

**Pill color buckets:**
- rank 1: green
- ranks 2–5: yellow
- ranks 6–20: orange
- ranks 21+: red
- null (song not in candidate pool): grey "—"

## API endpoints

### `GET /api/last-show` — metadata only

Fast DB query. Used by the picker page to decide whether to render the
footer link. Returns the most-recent show with `setlist_songs` rows where
`show_date` is before the same 11am-EDT rollover cutoff used by
`/upcoming`.

```json
{
  "show_id": 1764702466,
  "show_date": "2026-04-25",
  "venue": "Sphere",
  "city": "Las Vegas",
  "state": "NV",
  "run_position": 6,
  "run_length": 9
}
```

Returns **404** when no such show exists. The picker treats the 404 as a
signal to hide the footer link.

### `GET /api/last-show/review` — full review with ranks

Resolves the same show as `/last-show`, then assembles per-slot ranks
(cache-or-compute, see Cache section). Returns 404 in the same conditions.

```json
{
  "show": { "show_id": 1764702466, "show_date": "...", "venue": "...", ... },
  "slots": [
    {
      "slot_idx": 1,
      "set_number": "1",
      "position": 1,
      "actual_song_id": 613,
      "actual_song": "Timber (Jerry the Mule)",
      "actual_rank": 7
    },
    ...
  ]
}
```

`actual_rank` is the model's 1-indexed rank for the actual-played song
across all candidates. Null only when the song isn't in the candidate
pool — shouldn't happen for ingested songs.

**Why split into two endpoints**: the picker page must not pay a 5-second
worst-case compute (cache miss) just to render its footer link. The
metadata endpoint stays cheap; the heavy endpoint fires only when the user
actively navigates to the review.

## Cache schema + compute path

### Schema (added to `apply_schema`)

```sql
CREATE TABLE IF NOT EXISTS slot_predictions_cache (
    show_id INTEGER NOT NULL,
    model_sha TEXT NOT NULL,
    slot_idx INTEGER NOT NULL,
    actual_song_id INTEGER NOT NULL,
    actual_rank INTEGER,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (show_id, model_sha, slot_idx)
);
```

Trivially small: ~17 rows per show × however many shows we ever compute
× one entry per active model. Ten years of nightly shows under a single
model is ~6K rows.

### `model_sha` resolution

Computed once at API container startup:
`sha256(model.lgb)[:16]`. Stored on `app.state.scorer_sha`. Recomputed
on every container restart, which is automatically aligned with deploys
because deploys recreate the container. Heuristic fallback uses the
sentinel `"heuristic-v1"` so cache keys remain well-formed when LightGBM
fails to load.

### Compute path (cache miss)

1. Fetch setlist for `show_id` ordered by `(set_number, position)`.
2. Walk forward slot-by-slot exactly as `nightly-smoke` does: same
   `played_songs` accumulation, same `prev_set_number` / `prev_trans_mark`,
   same `slots_into_current_set` reset on set boundaries.
3. At each slot call `scorer.score_candidates(...)` over the full song
   pool, sort, locate the actual song's 1-indexed rank.
4. Insert all rows in one transaction keyed by
   `(show_id, model_sha, slot_idx)`.

### Cache hit

```sql
SELECT * FROM slot_predictions_cache
WHERE show_id = ? AND model_sha = ?
ORDER BY slot_idx
```

If row count equals setlist length, return assembled response. Anything
short of that is treated as a miss and recomputes.

### De-duplication with nightly-smoke

The slot-walking logic currently lives inside `phishpicker.nightly_smoke`.
Factor it out into a helper:

```python
# phishpicker/slot_ranks.py
def compute_slot_ranks(
    conn: sqlite3.Connection,
    *,
    show_id: int,
    scorer: Scorer,
) -> list[SlotRank]: ...
```

Both `nightly-smoke` and the new review endpoint call this. Eliminates
"two flavors of walk-forward" drift — the next time someone touches one,
they don't have to remember to mirror the other.

## Edge cases

| Case | Behavior |
|---|---|
| No completed show in DB | `/api/last-show` → 404 · picker hides footer link |
| Show ingested but no setlist yet | "most recent" query skips the row · falls back to the show before |
| First view after a deploy (`model_sha` changed) | Cache miss · ~5s compute · cached for that `(show_id, model_sha)` |
| Heuristic scorer fallback | Cache key uses sentinel · works · heuristic is fast anyway |
| 11am-EDT rollover transition | Atomic: `/upcoming` flips to next show and `/last-show` flips to last night's at the same boundary |
| Pull-to-refresh on review page | Re-fetches `/api/last-show/review` · cache stays valid · confirms freshness |

## Testing

**API (`test_last_show.py`)**
- 404 when no past show
- 200 metadata-only on `/last-show`
- 200 with computed slots on `/last-show/review`
- Cache hit returns same shape without recomputing (spy on scorer)
- `model_sha` change forces recompute (mock different SHAs)

**Cache helper (`test_slot_ranks.py`)**
- Pure function with a mocked scorer
- Walk-forward state matches `nightly-smoke` byte-for-byte
- `slots_into_current_set` resets on set boundaries
- `played_songs` accumulates correctly

**Web (`LastShow.test.tsx`)**
- Review page renders setlist with rank pills
- Color bucket logic (1=green, 2-5=yellow, 6-20=orange, 21+=red)
- Empty state / loading state
- Footer link in `page.tsx` shown only when `/api/last-show` returns 200

## Performance

**Compute cost**: 17 slots × ~970 candidates × `scorer.predict()`. Empirically
~5s for a full Sphere night during nightly-smoke runs.

**Cache hit cost**: one indexed SELECT (~1ms).

The review page can show a spinner during cold compute. After the first
hit per (show, model) pair, all subsequent loads are ~instant. With model
churn measured in days/weeks (a retrain is a deliberate action), the steady
state is "cache hit" almost always.

## Out of scope (deferred follow-ups)

- Bustout / LTP highlights (#5 mentions; cut from MVP)
- Browseable history past N-1 (a date picker / list view)
- Top-K alternatives per slot (the model's preferred picks alongside the
  actual)
- Cross-night residency comparisons ("this song's rank improved by 30
  across nights N4-N9")
- Sharing / permalinks to a specific past show

These can layer on top of the cache + endpoint without redesign.
