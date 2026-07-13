# Automated show close-out

**Status:** planned (2026-07-13)

## Problem

Nothing closes out a show. `finalize_scorecard` is only reachable via
`POST /live/show/{id}/scorecard`, whose only caller is `useScorecard` on the
`/recap` page. So last night's scorecard is written *lazily, the first time a
human opens recap* — and if nobody opens it, never. Worse, the score is computed
from `live_songs`, which only holds what was hand-entered plus whatever the
in-process sync poller reconciled while the app happened to be open. A night
spent actually watching the band leaves a half-empty, unscored show.

Two jobs, both in the existing `ingest-cron` sidecar.

## When is it safe to close out?

The interesting question, since waiting until the 11am ingest is far too late.

Two things rule out picking a clock time:

- **phish.net exposes no timestamp.** The v5 setlist row has no `updated_at` /
  `posted_at` — see the field dump in the commit that added this doc. We cannot
  ask "is this final?", only "what does it say right now?"
- **No single structural signal means 'done'.** An encore is the natural
  end-of-show marker, but only ~96% of shows have one (2015–2026: e.g. 47/48 in
  2025, 42/45 in 2024). Gating on `has encore` would hang forever on the rest.

So: **detect quiescence rather than guess an hour.** Poll the one show's setlist
and close out when it stops changing.

- `stable` = the setlist fingerprint (set, position, song) is non-empty and
  **identical across two consecutive polls** (`QUIET_POLLS = 2`, `POLL_EVERY =
  10min`) — i.e. ~20 minutes of no edits.
- `has_encore` is a *corroborating fast path*, not a gate: encore + stable is
  the common case and closes out promptly. An encore-less show still closes out
  on stability alone.
- Watch window opens at `WATCH_FROM = 22:30 America/New_York` on the show date
  and runs to the next 11am ingest, which is the backstop.

Polling stability — not a fixed hour — is also what makes this timezone-agnostic:
a west-coast show simply stays unstable longer and closes out when its data
lands. No venue-timezone table needed.

Cost is trivial: one `fetch_setlist_by_date` call per poll (not the ~2,250-call
full ingest), so the watcher is independent of the heavy 11am job.

**We do not yet know the real lag.** `close_out` logs the moment it fires and
how long after `WATCH_FROM` that was. After a handful of shows that gives an
empirical distribution, and `WATCH_FROM` / `QUIET_POLLS` can be tightened on
evidence.

## Why a pre-show freeze is now required

Scope is **every show**, not just ones tracked by hand. That means the job must
create the `live_show` row and freeze the bracket itself.

A bracket frozen at close-out time would be *leak-free but not credible*: every
model feature cutoff is `show_date < ?` (strictly before — verified across
`model/stats.py`, `train/extended_stats.py`, `train/bigrams.py`), so a bracket
computed the next morning genuinely cannot see the show it is predicting. But
"we froze our prediction the morning after" is indefensible the moment any of
this is published (#27/#28/#30). It must be frozen *before* the downbeat.

So the daily 11am pass also freezes tonight's bracket — ~8h before a 19:30 show.
`ensure_frozen` is a no-op when a bracket already exists, so a night you track by
hand is unaffected.

`ensure_frozen` MUST run before the first `live_songs` insert or it silently
drops the 60-pt opener pick (it reads entered songs from the DB and would return
the opener as an already-`entered` slot). `sync_show_with_phishnet` already
freezes before its append loop, so ordering is safe either way — but the pre-show
freeze makes it moot.

## Design

### 1. Pre-show freeze — daily, right after the 11am ingest

For today's show (rollover-adjusted): `create_live_show` (idempotent by date),
then `ensure_frozen`. No-op when already frozen.

### 2. Close-out watcher — from 22:30 ET on a show night

Every 10 minutes, for a show that's past `WATCH_FROM` and not yet finalized:

1. `fetch_setlist_by_date` → fingerprint.
2. Not stable yet → remember the fingerprint, wait for the next tick.
3. Stable → close out:
   - `sync_show_with_phishnet(scorer=<real scorer>, vapid_private_key="")`.
     - `scorer` non-None → `capture_snapshot` per append, so **live** points are
       credited exactly as if sync had been left on all night.
     - `vapid_private_key=""` → the per-song push branch is skipped, so this does
       **not** fire a push per song. No 3am setlist spam.
   - `finalize_scorecard` → persists the scorecard row.
   - Send **one** summary push: `"Last night: 85 pts — your 2nd best."`

### 3. Backstop — the 11am daily pass

Close out any past show that still has no scorecard (watcher missed it, container
was down, phish.net was late). Same path, so a straggler is scored identically.

## Idempotency

Everything re-entrant, which is what makes the backstop safe:

- `create_live_show` returns the existing row for that date.
- `ensure_frozen` no-ops when a bracket exists.
- `sync_show_with_phishnet` is an idempotent reconcile.
- `finalize_scorecard` is an upsert (`ON CONFLICT(show_id) DO UPDATE`), so a late
  phish.net correction cleanly re-scores on the next daily pass.
- The summary push is only sent on the transition to finalized (guard on the
  scorecard row not existing beforehand), so a re-score doesn't re-notify.

## Concurrency

The sidecar writes `live.db` while the API may also be writing it. Already safe:
`open_db` sets `busy_timeout=15000` and WAL is a persistent property of the file,
so the second writer waits rather than raising `database is locked`.

## Out of scope

- Venue-timezone table (stability detection makes it unnecessary).
- Reducing the daily ingest's ~2,250 setlist calls.
