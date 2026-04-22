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

All under `/api/picker/`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/upcoming` | Next Phish show (date, venue, city, show_id) |
| GET | `/sessions/{date}` | Current session state (entered songs, set, predictions, sync status) |
| POST | `/sessions/{date}/songs` | Append an entered song (body: `{song_id, set_number}`) |
| DELETE | `/sessions/{date}/songs/last` | Undo last entry |
| POST | `/sessions/{date}/sets/end` | Advance to next set (body: `{current_set: "1" | "2"}`) |
| POST | `/sessions/{date}/slots/append` | Add an extra predicted slot to a set |
| GET | `/sessions/{date}/predictions` | Full predicted setlist (grayed preview — autoregressive top-1 per slot + top-10 alts per slot) |
| GET | `/sessions/{date}/slots/{idx}/alternatives` | Top-10 alts for one slot |
| GET | `/songs?q=<prefix>` | Typeahead search |
| POST | `/songs` | Insert bustout placeholder (body: `{name}`, sets `is_bustout_placeholder=1`) |
| POST | `/sessions/{date}/sync/toggle` | Enable/disable phish.net auto-sync |

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

One JSON blob per `show_date`. Stored server-side in
`api/data/picker-sessions/<date>.json` (new directory, git-ignored).

```ts
interface PickerSession {
  show_date: string;              // "2026-04-23"
  show_id: number | null;         // phish.net showid
  venue: string;
  city: string;
  state: string;
  entered_songs: EnteredSong[];   // user + phish.net merged
  structure: SetStructure;        // current slot count per set
  sync_enabled: boolean;
  sync_status: "live" | "stale" | "dead" | "off";
  sync_last_updated: string | null;
  sync_last_error: string | null;
  created_at: string;
  updated_at: string;
}

interface EnteredSong {
  song_id: number;
  name: string;                   // denormalized for client speed
  set_number: string;             // "1" | "2" | "E"
  position: number;               // within-set 1-indexed
  source: "user" | "phishnet";
  superseded_by?: number;         // song_id, if phish.net overrode
  entered_at: string;
}

interface SetStructure {
  set1: number;  // default 9
  set2: number;  // default 7
  encore: number; // default 2
}
```

LocalStorage mirrors this on the client for instant restore.

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
