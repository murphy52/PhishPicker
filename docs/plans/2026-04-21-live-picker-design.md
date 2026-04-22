# Live Picker UI — Design

**Date:** 2026-04-21
**Status:** Design approved, implementation plan pending
**Goal:** A personal, mobile-friendly React app for watching v10's predictions
compete with Phish live during the Sphere residency (Nights 4-9). Primary use
case: David is at Nights 7, 8, 9 in person (4/30, 5/1, 5/2); remote use for
earlier nights.

## Primary use case

Open the app when doors open. It auto-loads tonight's show, shows a full
grayed-out predicted setlist (9/7/2 by default), and passively tracks
phish.net for live setlist updates. As each song plays, it appears in the
app (auto-synced or manually entered), and all downstream predictions
recompute. David can tap any slot to see the top-10 alternatives.

## Out of scope

- Multi-user accounts / auth (personal tool, private Cloudflare tunnel)
- Offline mode (live-only tool; if connection dies, tool is dead)
- Probability calibration (raw LightGBM scores aren't probabilities; show
  rank + song name only)
- "Why this song?" feature-contribution debugging (defer)
- Historical setlist browser (separate future feature)
- Post-show reconciliation UI (separate feature; feeds retro harness)
- Desktop-optimized layout (mobile-first; desktop is "larger mobile")

## Tech stack

- **Frontend:** React (Next.js 15 App Router). TypeScript everywhere.
  Tailwind for styling. No component library — hand-rolled to stay distinct.
- **Backend:** Extend existing FastAPI app (`api/src/phishpicker/`). New
  endpoints in `api/src/phishpicker/live_picker.py` (mirroring the
  `nightly_smoke.py` pattern).
- **State:** Server-side session keyed by `show_date` (single user). Client
  polls server every 5s. LocalStorage redundancy for instant restore on
  reload.
- **phish.net sync:** Server-side polling (1 poller per show, not per
  client) every 60s during show hours.
- **Deploy:** Same docker-compose stack on NAS; web app served alongside
  the API behind the existing Cloudflare tunnel.

## Revision note (post-team-review, 2026-04-21)

This section supersedes conflicting earlier design choices:

- **State of record is SQLite**, not a JSON blob. The existing `live_show` /
  `live_songs` tables hold what actually played. A new `live_show_meta`
  table holds per-show metadata: sync state (`sync_enabled`, `last_updated`,
  `last_error`), structure overrides. Two new columns on `live_songs`
  support reconciliation: `source` (`"user" | "phishnet"`) and
  `superseded_by` (song_id, when phish.net overrode a user entry). No JSON
  blob; no `api/data/picker-sessions/` directory.
- **Preview is stateless.** The backend exposes a pure `POST /predict`
  endpoint accepting `{played_songs, current_set, show_date, venue_id}`
  and returning top-K. The full 9/7/2 preview is a loop — either on the
  client or in a convenience server endpoint — calling `/predict` once per
  slot, extending `played_songs` with the top-1 each iteration. No hidden
  autoregressive state in the server.
- **Timezone is explicit.** `/upcoming` returns `timezone`
  (e.g. `"America/Los_Angeles"`) and `start_time_local` (e.g. `"19:00"`)
  alongside date/venue/city/state. The client combines these with the
  browser's own `Intl.DateTimeFormat().resolvedOptions().timeZone` to
  render a correct countdown regardless of where the user is.
- **Override is full.** `replace_song_at(conn, show_id, entered_order,
  new_song_id)` is a first-class DB helper. Interior phish.net overrides
  work the same as tail appends. No "punt and warn" for interior slots.
- **Poller lives on `app.state`** as a `PollerRegistry` instance, not a
  module-level global. Tests get a fresh registry per `TestClient`; teardown
  cancels any live tasks. Poller opens its own DB connection inside each
  tick (avoids `sqlite3` thread-affinity traps with `asyncio.to_thread`).

Everything below that implies a JSON blob, shared global `_POLLERS`, or
timezone-naive "today" should be read through this lens.

## Frontend layout (mobile-first)

```
┌─────────────────────────────────┐
│ 2026-04-23 · Sphere · Las Vegas │  ← header
│ [Live: updated 1m ago ●]        │  ← sync status pill
├─────────────────────────────────┤
│ SET 1                           │
│ ▸ 1. Buried Alive       ✓       │  ← entered (solid)
│ ▸ 2. Moma Dance               3 │  ← predicted (gray, shows rank-in-top)
│ ▸ 3. Sample in a Jar            │
│ ...                             │
│ [+ Add song to Set 1]           │
│ [End Set 1 →]                   │
├─────────────────────────────────┤
│ SET 2  (grayed out until live)  │
│ ...                             │
├─────────────────────────────────┤
│ ENCORE                          │
│ ...                             │
├─────────────────────────────────┤
│ [Enter current song      ][Undo]│  ← sticky footer
└─────────────────────────────────┘
```

Tapping a grayed slot opens a modal listing top-10 alternatives with their
scores. Solid (entered) slots open a smaller panel allowing edit/undo.

## API surface

**Authoritative list is in the implementation plan, keyed on the existing
`/live/*` endpoints + new stateless `POST /predict` + sync endpoints.**
The earlier `/api/picker/sessions/*` shape in this section was obsoleted by
the revision note above; the implementation uses the SQLite-backed
`/live/show/{id}/*` endpoints directly.

## phish.net live sync

**Who polls:** Backend, one poller per show, singleton task. Started when
a client first requests `/upcoming` and the returned date is today, or
explicitly via `/sessions/{date}/sync/toggle?enable=true`.

**Cadence:** 60s during show hours (local 7pm-1am ET on show days).
Otherwise 5min (cheap keepalive).

**Endpoint:** `setlists/showdate/{date}.json` (already used by
`nightly_smoke.py`). Same client: `PhishNetClient`.

**Reconciliation logic** (runs inside the poller on each fetch):

Let `user_rows` = session's entered songs, `net_rows` = phish.net's rows
for the show (sorted by set/position).

For each index i in `max(len(user_rows), len(net_rows))`:

| Case | Action |
|---|---|
| `i >= len(user_rows)` and `i < len(net_rows)` | Append `net_rows[i]`; trigger re-prediction. No UI popup. |
| `i < len(user_rows)` and `i >= len(net_rows)` | No-op. User is ahead of phish.net. |
| Both present, same `song_id` | No-op. |
| Both present, different `song_id` | phish.net wins. Toast: "phish.net updated slot N: X → Y." Keep `previous_entry` so user can one-tap revert. |
| phish.net song not in local `songs` table | Insert with `is_bustout_placeholder=1`; proceed as normal append. |

**Sync status states:** `live` (update < 2min ago), `stale`
(2-10min), `dead` (>10min or poller errored 3x), `off` (user disabled).

## Session state model

See the **Revision note** section above. State lives in SQLite
(`live_show`, `live_songs`, and a new `live_show_meta` table). `live_songs`
gains `source TEXT` and `superseded_by INTEGER` columns for
reconciliation history. `live_show_meta` holds `sync_enabled`,
`last_updated`, `last_error`, and per-show structure (`set1_size`,
`set2_size`, `encore_size`). No JSON blob, no `picker-sessions/` directory.

LocalStorage mirrors the live-show id + last-known predictions for instant
phone-reload restore, but it is never the authoritative store.

## Predictions model

`GET /sessions/{date}/predictions` returns:

```ts
interface PredictionsResponse {
  slots: PredictedSlot[];
  computed_at: string;
}

interface PredictedSlot {
  slot_idx: number;
  set_number: string;            // "1" | "2" | "E"
  position: number;              // within-set
  state: "entered" | "predicted";
  // when "entered":
  entered_song?: EnteredSong;
  entered_song_rank_in_preview?: number | null;  // where this landed in model's top-K
  // when "predicted":
  top_k?: { song_id: number; name: string; score: number; rank: number }[];
}
```

The backend computes this by:
1. Starting from `entered_songs` as the played-list.
2. For each remaining slot in `structure`, calling `predict_next()` and
   picking top-1 as the "preview" pick, rolling that into played-list.
3. Also returning top-10 alts for each slot for the modal.

Recomputed on every song entry + every phish.net sync update.

## Bustout handling

Typeahead returns 0 matches → offers "Add 'xyz' as new song?" → POST
`/songs` with `is_bustout_placeholder: true`. This:

- Inserts into `songs` table with the new flag
- Flag is surfaced in post-show reconciliation: "You or phish.net added N
  songs as bustouts this show — verify against phish.net authoritative
  song list tomorrow."
- Doesn't break `predict_next` (the song is now a candidate; its feature
  vector has sparse/default values, so it'll rank low — which is correct
  for an unknown bustout).

Schema change needed:
```sql
ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER DEFAULT 0;
```

## Testing

- **Backend unit tests** (`api/tests/test_live_picker.py`):
  - Session CRUD (create, append song, undo, end-set, extend structure)
  - Reconciliation: 5 cases from the table above
  - Predictions endpoint integrates correctly with `predict_next`
  - Bustout insert + typeahead
- **phish.net poll loop** mocked with `pytest-httpx` (same pattern as
  `test_nightly_smoke.py`)
- **Frontend**: minimal — smoke test that the page renders with mocked
  API. No full E2E; this is a personal tool, testing effort is capped.

## Milestones

1. **Backend complete, API callable end-to-end** — can hit `/upcoming`
   and `/sessions/.../songs` with curl and see predictions update.
2. **React app shell with typeahead + entry flow working** — no phish.net
   sync yet. Manual-only path verified.
3. **phish.net poller integrated** — auto-append works end-to-end.
4. **Deploy to NAS** — Cloudflare tunnel, mobile test, ship.
5. **Stretch, post-Night-4**: reconciliation view, polish.

Target: working end-to-end by Sunday 2026-04-26 (Night 6). Nights 4-5
(4/23, 4/24) use the CLI retro harness as fallback. Nights 7-9 (4/30,
5/1, 5/2) are the in-person target — fully live tool.

## File inventory (new)

Backend:
- `api/src/phishpicker/live_picker.py` — session management, reconciliation
- `api/src/phishpicker/live_picker_api.py` — FastAPI routes (or add to existing `api.py`)
- `api/src/phishpicker/phishnet/poller.py` — background poll task
- `api/tests/test_live_picker.py` — unit tests
- Schema migration: `is_bustout_placeholder` column

Frontend (new top-level `web/` directory):
- `web/` — Next.js 15 app
- `web/app/page.tsx` — main picker page
- `web/app/api/` — server route handlers (proxy to FastAPI if needed)
- `web/components/` — ShowHeader, SetList, Slot, TypeaheadInput, etc.
- `web/lib/api.ts` — typed client for `/api/picker/*`

Docker:
- `web/Dockerfile` — Node build
- Update `docker-compose.yml` — add `web` service, share Cloudflare tunnel

## Open questions (defer until implementation)

- **Scoring display format in the alts modal.** Raw LightGBM scores are
  comparable-within-slot but not interpretable. Show as-is, or normalize
  relative to top-1? Decide during frontend build.
- **"End Set 1" behavior when Set 1 has fewer entries than default 9.**
  Just advance — the gray slots below collapse. Fine.
- **What to do when phish.net and user agree except for case/spacing
  (e.g. "Tweezer Reprise" vs "Tweezer Rep.").** Normalize on song_id, not
  name. phish.net returns `songid`; we use that as the join key. Name
  mismatches are cosmetic only.
- **Rate-limiting phish.net.** `nightly_smoke.py` doesn't rate-limit;
  60s poll is well below any reasonable limit. Monitor for errors.
