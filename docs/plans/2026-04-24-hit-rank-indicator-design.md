# Hit-rank indicator on entered slots

Design doc for GitHub issue #6 ("Show a target icon when the prediction is correct").

## Goal

On the `/upcoming` view, show each entered song's rank in the model's prediction for that slot. The bullseye case (rank 1) gets a target icon; other ranks in the top-10 get a number; songs outside the top-10 get an em-dash.

## Rank semantics: retroactive

Rank is computed **retroactively** given fixed prior context. For each entered slot, treat every prior entered slot (ordered by `slot_idx`) as known, then score candidates for this slot using the same pipeline that produces predictions today. The entered song's 1-based position in that ranking is `hit_rank`.

Chosen over two alternatives:

- *Snapshot at entry time* — would require persisting the top-K at the moment a slot transitions predicted→entered. More machinery; sensitive to UI timing.
- *Pre-show rank* — doesn't reflect how the model performed during the show, since predictions are rolling.

Retroactive rank is stable (doesn't depend on UI timing), matches what the alternatives modal already computes, and degrades gracefully to past shows.

## Data model

Add one field to `PreviewSlot`:

```ts
hit_rank: number | null  // 1..10 if the entered song was in top-10, else null
```

Populated only when `state === "entered"`. Predicted slots keep the current shape.

## Backend — `api/src/phishpicker/live_preview.py`

For each entered slot, compute the ranked candidate list with prior entered slots as context. Find the entered song's 1-based index in the ranking:

- In top-10 → set `hit_rank`.
- Outside top-10, or song not in the candidate pool → null.

Returned inside `/preview` so the view gets rank + prediction in one round-trip. Top-K candidates continue to be returned on predicted slots only; entered slots carry just `hit_rank` (no `top_k`).

Cost: one extra scoring pass per entered slot, already cheap at current pool sizes.

## Frontend — `web/src/components/FullPreview.tsx`

In the `entered` branch of `SlotRow` (line 59), append a right-aligned indicator after the song name:

- `hit_rank === 1` → small target-icon SVG (concentric-circle bullseye), ~14px, `text-emerald-400`.
- `hit_rank >= 2 && hit_rank <= 10` → `#N` in `text-xs text-neutral-500 tabular-nums` — visually parallels the `%` chip on predicted slots.
- `hit_rank == null` → `—` in `text-xs text-neutral-700`.
- During `pending === "adding"` → suppress the indicator; the spinner already communicates in-flight state and `hit_rank` arrives when the slot settles.

Applies to both user-entered and phish.net-reconciled songs — rank depends on slot + prior context, not on source.

## Testing

**Backend** (`api/tests/`)
- `hit_rank == 1` when entered song is the top candidate.
- `hit_rank == N` for a mid-rank hit.
- `hit_rank == null` when entered song is outside top-10.
- `hit_rank == null` when entered song is not in the candidate pool at all.

**Frontend** (`web/src/components/FullPreview.test.tsx`)
- Rank-1 renders target icon.
- Rank-N (e.g., 3) renders the `#N` chip.
- `hit_rank == null` renders em-dash.
- `pending === "adding"` suppresses the indicator.

## Out of scope

- Aggregate live-show accuracy display (e.g., "5/12 top-1" summary). Followup.
- Snapshot-at-entry-time rank. Rejected above.
- On-demand fetch per slot via `/alternatives`. Rejected — embedded in `/preview`.
