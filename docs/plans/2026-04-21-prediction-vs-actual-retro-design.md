# Prediction-vs-Actual Retrospective — Design

**Date:** 2026-04-21
**Status:** Design approved, plan pending
**Motivation:** Night 4 of the Sphere residency (Thu 2026-04-23) is the first
real-world test of v10's residency-aware features. We need a repeatable harness
to retrospect each night's predictions against what Phish actually played, so
the accumulating JSONL + preview artifacts answer the three open research
questions in RESUME.md:

1. Does v10's front-loaded A-list pacing match reality?
2. By Night 9, do we see top-10 leak growth matching the Baker's Dozen
   diagnosis?
3. Do the per-case winners (Buried-Alive-#1-style) generalize to Night 4+?

## Architecture

Three artifacts, two timelines.

**Preview-save time (before each night):**
- `preview_night4.py` runs and also writes `api/data/previews/preview-YYYY-MM-DD.json`.
- `preview_residency.py` runs and also writes `api/data/previews/forward-sim-YYYY-MM-DD.json`
  (invocation date in filename; payload covers all 6 nights).

**Retrospective time (morning after each night, post-ingest + post-smoke-cron):**
- `scripts/compare_prediction_to_actual.py --date YYYY-MM-DD` consumes:
  1. Saved preview JSON (ahead-of-show autoregressive prediction)
  2. Actual setlist from `phishpicker.db` (`shows` + `setlist_songs`)
  3. Nightly-smoke record from `api/data/nightly-predictions.jsonl`
- Emits stdout summary + markdown artifact at
  `docs/retros/night-N-retro-YYYY-MM-DD.md`.

```
preview_night4.py ─────────► preview-YYYY-MM-DD.json ─┐
                                                      │
phish.net → ingest → DB ─► actual setlist ────────────┼─► compare.py ─► stdout
                                                      │              ─► retro.md
nightly_smoke cron ────────► nightly-predictions.jsonl┘
```

## Preview-save changes

**Schema (both scripts conform):**
```json
{
  "show_date": "2026-04-23",
  "venue_id": 1597,
  "generated_at": "2026-04-21T15:30:00Z",
  "model_path": "data/model.lgb",
  "pass": "RAW",
  "picks": [
    {"slot_idx": 1, "set": "SET 1", "song_id": 123, "name": "Buried Alive"}
  ]
}
```

`preview_residency.py` wraps the same `picks` shape in a top-level
`{"nights": [...]}` with one element per night.

**`preview_night4.py`:** Only RAW is saved — that's the honest
"what the model thinks will happen" trajectory. FILTERED was a
v10-validation tool.

**`preview_residency.py`:** One file per invocation, filename uses the
generation date so re-runs don't clobber history.

## Compare script

CLI: `~/.local/bin/uv run python scripts/compare_prediction_to_actual.py --date 2026-04-23`

**Library-first layout** (`api/src/phishpicker/retro.py`):
```python
def load_preview(path: Path) -> PreviewDoc
def load_actual_setlist(conn, show_date: str) -> list[ActualSlot]
def load_smoke_record(jsonl_path: Path, date: str) -> SmokeRecord | None
def compare(preview: PreviewDoc, actual: list[ActualSlot],
            smoke: SmokeRecord | None) -> Retro
def render_markdown(retro: Retro) -> str
def render_stdout_summary(retro: Retro) -> str
```

The `scripts/compare_prediction_to_actual.py` file is thin glue — all logic
is unit-testable via `retro.py`.

### `Retro` analyses

1. **Set-level overlap** — `preview ∩ actual` as a fraction of each. Addresses
   pacing (Q1) and leak growth at set granularity (Q2).
2. **Slot-level match** — did slot i in preview equal slot i in actual? Exact
   plus off-by-N counts.
3. **Rank-of-actual-in-preview** — for each actual song, position in the
   preview ranked list (reconstructed from the preview's pick order; absent
   songs flagged "not predicted"). Addresses per-case winners (Q3).
4. **Per-slot rank from nightly-smoke** — median/Top-1/Top-5/Top-10 of
   `actual_rank` pulled from JSONL. The already-captured measurement.

### Markdown template

```markdown
# Night N Retro — YYYY-MM-DD Venue

## Headline
- Preview picks: 18 slots · Actual slots: N
- Preview∩Actual: K songs (X% of preview songs were played)
- Nightly-smoke: Top-1 A/N · Top-5 B/N · median rank R

## Slot-level
| Slot | Predicted | Actual | Match |

## Where did the preview miss?
[Actual songs NOT in preview, with smoke-recorded rank if available]

## Where did the preview over-commit?
[Predicted songs that didn't appear]

## Compared to model evolution
v7 headline: Top-1 6.8% Top-5 21.2% — this night: …
```

## Testing

TDD in `api/tests/test_retro.py`:
- Synthetic preview + synthetic actual → expected set overlap
- Mismatched slot counts (preview 18, actual 17) → graceful handling
- Missing smoke record → retro still renders (smoke section omitted)
- Markdown rendering determinism (string assertion or golden file)

No script-level integration test (the script is pure glue over the library).

## Error handling

| Missing input | Behavior |
|---|---|
| Preview JSON absent | Hard error with path + pointer to re-run preview script |
| Actual setlist absent | Hard error: "run `phishpicker ingest` for date X first" |
| Smoke JSONL absent or no record for date | Warn + render retro without smoke section |

## Out of scope

- Auto-running preview_night4 / preview_residency as cron (user-triggered).
- Automatic post-to-chat or email of the retro.
- Cross-night aggregate (a separate follow-up script can aggregate the
  per-night retros once 2+ exist).
- The v11 feature design itself (`run_saturation_pressure`,
  `slots_into_current_set`) — that's queued for post-Sphere per RESUME.md.

## File inventory

New:
- `api/src/phishpicker/retro.py` — library
- `api/tests/test_retro.py` — unit tests
- `scripts/compare_prediction_to_actual.py` — CLI glue
- `api/data/previews/` — preview JSON storage (directory)
- `docs/retros/` — retro markdown storage (directory)

Modified:
- `scripts/preview_night4.py` — adds `save_preview()` call
- `scripts/preview_residency.py` — adds equivalent save at end
