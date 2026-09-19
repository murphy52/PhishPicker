# Phish vs Fans vs PhishPicker — design

**Status:** v2, 2026-09-19. v1 approved same day, then revised after four expert
reviews (Cloudflare architecture, game design, mobile UX, Phish/phish.net
domain). Separate project: `murphy52/phishvs`, local `~/phishvs`. This copy
stays in phishpicker as the record of the seam between the two.

**Launch:** soft launch on the Fall 2026 tour opener, **Oct 2, 2026** (Boardwalk
Hall, Atlantic City), with friends. See "Oct 2 scope" — it is deliberately a
fraction of this doc. Everything else lands during the tour or after.

## What it is

A public PWA where Phish fans predict tonight's setlist as a bracket and score
against the band. Three sides play every show:

- **Phish** scores when they play what a bracket didn't predict. The more they
  deviate, the more they score. If Phish wins, everyone wins.
- **PhishPicker** — the model's frozen bracket, scored exactly like a fan's. It
  is "Phish being predictable."
- **Fans** — each fan individually, and later collectively as **The Fans**, a
  consensus bracket.

Phishpicker (this repo) stays private and single-user. It trains locally, runs
on the NAS, and *publishes* artifacts to the game. It never serves the game.

## Principles

- **One goal at level zero.** *Pick tonight's setlist. Songs you call are your
  points. Songs you miss are Phish's. Beat Phish.*
- **Progressive disclosure.** Leagues are the first social layer, not the first
  goal — most launch users won't be in one. PhishPicker is revealed in the
  recap, not explained up front ("Your suggestions came from PhishPicker, our
  model. It scored 58. You scored 62.").
- **User journeys drive every screen.** Journeys 1 and 5 are the launch.
- **Symmetric fairness.** Every bracket is built on the identical published
  shape and scored by the identical pure function. Structure surprises never
  advantage anyone; they shift points toward Phish.
- **Indisputable results.** Leagues will run their own pools. The app has zero
  wagering features and holds no funds; it makes standings, tie-breaks, and
  finality airtight so nobody has to argue.
- **UX first, style later.** All color/type/spacing/radius are design tokens
  (CSS variables → Tailwind theme) with semantic names (`surface`,
  `accent-phish`, `accent-fans`, `accent-picker`); components never use raw
  values. Build on a plain neutral set; polish is a token swap plus
  motion/iconography. Three sides always get glyph + label + color, never
  color alone. Both color schemes from day one (parking lot at 6pm is daylight).
- **Honest about latency.** phish.net's API is server-cached ~5 min and entries
  lag the stage. The rules page says live scoring trails the show by 5–10 min.
  Never say "real-time."

## User journeys

1. **Stranger, show tonight** (launch-critical). Link → landing *is* the
   builder, already filled → tinker → **Play this bracket** → Google sign-in →
   "You're in" screen. Launch metric: **landing → commit under 2 minutes**
   (one analytics event).
2. **Stranger, no show soon.** Next show + countdown, "Add to calendar" (.ics,
   no account), "Send to your crew," "See last night" (read-only recap). No
   sign-in push here — the chain (sign in → install → permission) is too long
   for someone with nothing to play.
3. **Returning solo player, show day.** Morning push ("Phish leads you 3–2.
   Tonight's bracket is ready.") → picks → lock → live → recap.
4. **League creator.** Create (name only) → share link → watch friends appear.
5. **Invited friend.** Invite link lands on the **builder** with a slim banner
   ("Dave invited you to Couch Tour Crew — you join when you play"). Auto-join
   at commit. Already signed in: join now, toast, builder. No show soon:
   journey 2 with the league remembered. The builder is always reached from
   the show, never from a league.
6. **Live show.** Hero score, rank, feed; one tap to level 2.
7. **Morning after.** Recap: series record vs Phish, did you beat PhishPicker
   (the reveal), league finish.
8. **Explorer.** Everything at level 3 — findable, never forced.

### Disclosure ladder

| level | who | what |
|---|---|---|
| 0 | everyone | builder (pre-filled; per-slot re-roll; tap-to-swap; search); goal sentence; lock countdown; "N of 18 changed" |
| 1 | after lock / live | ME vs PHISH hero; league rank or "top 22% of fans"; feed |
| 2 | one tap | PhishPicker row ("the model behind your suggestions"); later The Fans |
| 3 | explorer | tour/all-time boards, profile stats & badges, consensus detail, "show odds" |

## Game rules

**Entries.** One bracket per **user × show** — never per league (invariant
below). Shape = the published structure for the show (default S1×9, S2×7,
E×2; 91% of shows since 2015 are S1/S2/E with means 9.0 / 7.1 / 2.2; known
3-set nights are published with 3 sets). Skipping shows is fine.

**Lock.** phish.net has no showtime field. Each show carries an **admin-entered
`scheduled_start`** (default 19:30 venue-local; required before the show
opens), from which `lock_at` is stored as a UTC instant at publish. The server
rejects edits at `now ≥ lock_at`; the client countdown is cosmetic. The
coordinator polls from **T−30**; if any setlist entry is first seen before
`lock_at`, the effective lock becomes `first_seen − 5 min`, later edits are
reverted, PhishPicker freezes at the same instant, and a labeled correction
event is emitted. Late starts change nothing.

**Scoring** — VS-calibrated constants (`scoring.py`, `VS_PICKER`), identical for
every fan bracket, PhishPicker, and The Fans. Consume-once: each played song is
claimed by at most one pick. Recompute from the full setlist every time; never
incremental.

| tier | pts |
|---|---|
| set opener (S1.1, S2.1, S3.1, E.1) | 20 |
| exact slot | 16 |
| right set, wrong slot | 10 |
| played, wrong set | 6 |

**Phish**, against a given bracket, scores every played song absent from it:
**base 3**, **+6 bustout** (gap ≥ 100 shows, or debut / not in catalog — this
is what `scoring.py` already does via `VS_BAND_GAP_BUSTOUT_MIN`), **+2 rare
(gap ≥ 50)**. *Decided 2026-09-19:* rare is gap-based, replacing `<50
all-time plays` (which flagged 39% of songs played since 2024 — a
new-material bonus, not rarity). Changed in **both** scorers; phishpicker's
Jul-12/14 contract test is re-run to confirm calibration still reads as a fair
coin (re-derived 2026-09-19: Jul 12 = 122–15 picker, Jul 14 = 24–39 phish; the
exported fixture originally carried phish.net's show-monotonic positions, which
undercounted S2/encore openers — fixed to within-set positions, matching prod —
both leaders hold). Gap is taken from the first occurrence in a show (repeat
rows report 0).

Phish's score is **relative to an opponent**. It is presented as **pairwise
duels** — "Phish vs you," "Phish vs PhishPicker," later "Phish vs The Fans" —
never as one number in a three-way row, and never as a ranked league member.

Repeats: first play claimed by the pick, second goes to Phish (sandwiches and
`Jam` are unpredictable by design). Reprises are distinct song ids. Soundcheck
and `exclude == 1` rows ignored.

No streaks/combos in v1. No "beat the picker" points. **🎯 upset** badge =
song absent from PhishPicker's frozen bracket **and hand-pinned** by the fan;
0 pts, counted in the recap.

**Rounding out the win condition.** ~20 songs, 18 picks, hits pay ≥ 6, misses
pay Phish ~3.4 avg → "beat Phish" ≈ hit more than ~30% of the setlist. The
model does that ~3 nights in 8; a tinkering fan lands ~25–40%. Achievable, not
trivial. A sampled bracket is worse in expectation than the model's top-1, so
lazy fans lose to PhishPicker most nights — recaps say "PhishPicker edged you
by 4," never "you lost."

**The Fans (consensus).** Computed at lock over **hand-pinned picks only**
(auto-filled slots don't vote, or the crowd is just the model); most-pinned
song per slot, ties by the frozen bundle's probability at lock; slots nobody
pinned are "no call" (score 0). Frozen; scored like any bracket. **Computed
from launch, displayed later.**

**Boards.** Per show: **Mine** (Me vs Phish, Me vs PhishPicker, "top N% of
fans"), **League** (members ranked; PhishPicker as a reference row), **Global**
(duels + fan percentile). Running boards per show / run / tour / all-time.
Run = consecutive shows, same venue id, same tour id. Tour = phish.net
`tour_name` (no "leg" concept exists; custom date range covers legs).

**Retention mechanic: the series.** "Phish leads you 3–2 this tour" is the
hero of every recap and the morning push. Already computed (nights beat
Phish); zero scoring change. On multi-night runs the previous bracket is
carried forward with "played last night" slots flagged for one-tap re-roll.

### Structure exceptions (all on the public rules page)

- **Set length differs** (every show): nothing thrown out. Picks beyond the
  actual length can't be exact but still score right-set / somewhere. Extra
  actual songs go to Phish unless someone had them.
- **Fewer sets than the shape** (rain/curfew → one set): **no remap.** S2 picks
  that were played score *somewhere* (6). Symmetric, zero code, and it keeps
  the principle that surprises shift points toward Phish. (v1's "join sets
  end-to-end" rule is withdrawn — it silently promoted every hit to 10.)
- **More sets than the shape** (surprise S3): S3 songs score *somewhere* for
  anyone who had them, Phish otherwise.
- **Postponed:** show record moves, brackets carry over, editing reopens until
  the new lock. (Admin-manual at launch.)
- **Cancelled:** voided — no scores, dropped from "N of M shows." Admin must
  set `cancelled`; a cancelled show never reaches quiescence on its own.
- **Set-label churn:** encore posted as Set 3 then corrected (or vice versa)
  flips a 20-pt call. Re-score on correction; feed shows "corrected: Set 3 →
  Encore"; set-break pushes wait one poll after a new set label appears.
- **Weird data:** admin can force a structure and re-score; surfaces as a
  labeled correction.

### Provisional → Final

Close-out on quiescence, both gates ported from `close_out.py`: `now ≥ 22:30`
venue tz **and** unchanged ≥ 20 min, encore as corroboration, noon-next-day
backstop → **provisional**, recap push. **Final after 72h** (phish.net edits
setlists 3–9 days out per `updated_at` on real shows). A **daily re-poll
through season end** re-scores and emits a labeled correction + re-materializes
standings if anything changed, even after final. A season is final 72h after
its last show.

## Leagues

- Create (name only); join by invite code/link; unlimited members; many
  leagues per user; global = "everyone."
- **Invariant:** brackets are user × show. Leagues never own brackets; a league
  season is a scope (shows) + roster (users); standings are computed over
  `scores` for that intersection. One bracket counts in every league. Never
  add `league_id` to `brackets`; never imply "your bracket for this league."
- **Seasons:** at launch every league implicitly has two boards, **tonight**
  and **this tour** (from `tour_name`) — no configuration. Later: explicit
  scope = show / run / tour / custom date range, join deadline.
- **Commissioner** (creator): remove members (launch); close joining, join
  deadline, notes (later).
- **League notes** (later): free-text, pinned, rendered verbatim, never parsed.
  Where a league writes whatever rules it wants among itself.
- **Tie-breaks**, deterministic and on the page: total points → *(multi-show
  seasons only:)* nights beat Phish → exact/opener hits → songs hit → **shared
  place** ("ties split"). No earliest-locked gimmick.
- Podium (1st/2nd/3rd) and nightly league winner callouts; missed shows score
  0 and standings show "8 of 9 shows"; after lock every member's bracket is
  visible to the league with its lock time; roster shows join time + avatar.
- Share: OG text on `/l/:code` and `/s/:date`; generated images later.
- Terms: no wagering features, no funds held; multiple accounts are tolerated,
  not fought. Footer + rules: "setlist data courtesy of phish.net."

## Bracket builder

- **Always start complete.** First open → bracket **sampled** from the model's
  per-slot band — never the top-1 (or everyone who commits untouched ties
  PhishPicker and the reveal is dead). PhishPicker's frozen entry *is* top-1.
- **Re-roll per slot** (no global shuffle competing with the CTA). Sample from
  candidates within a probability band of the slot's top pick, weighted; **no
  song twice in a bracket**; `Jam` / `Intro` excluded from candidates.
  Hand-picked slots are **pinned** and survive re-rolls. Band and cap are
  tuned by measuring pairwise Jaccard between auto-fills on real `top_k`
  (target ≤ 0.6, i.e. ≥ 7 differing slots; start at ≥ 40% / cap 6, widen to ≥
  25% / cap 8 if too similar).
- **Tap a slot → picker sheet:** 6–8 suggested chips with **gap** ("last played
  14 shows ago") and a subtle likelihood bar; search over the catalog (fuse.js,
  from `AddSongSheet`); a **"Move to another slot"** row → swap mode (other
  slots pulse, Cancel bar) → tap destination. One interaction model. **No drag
  at launch** (grip-handle drag in v1.1 if asked).
- **Ownership nudges, not points:** "N of 18 changed" beside the CTA; "You
  differ from PhishPicker in N slots" on the confirm screen; post-lock
  ownership % on each pick ("61% of fans"); league view highlights each
  member's unique picks.
- **Commit:** **Play this bracket.** Tap count to commit: 1 + OAuth, zero
  required edits. The entry exists from that moment; edits auto-save
  (debounced ≥ 2s, one row per bracket with picks JSON) until lock.
- **"You're in" screen:** countdown + edit link + **one** secondary action —
  Android/standalone: "Notify me at set breaks" (native prompt fires only on
  tap); iOS Safari: a dismissible "Get set-break scores: Share → Add to Home
  Screen" card. Nothing else.
- Empty slots after commit score 0 and don't vote in consensus; T−60 push
  nudges empties. Never auto-fill on someone's behalf after commit.

## Sign-in, identity, notifications

- **Google only at launch** (recommended by 3 of 4 reviews). Apple Sign-In
  needs a $99/yr developer account, an ES256 client-secret JWT rotated ≤ 6 mo,
  and Better Auth's Apple `form_post` callback has a known `state`-cookie
  footgun. A PWA has no App Store obligation to offer it. Revisit after tour.
- **Better Auth** on Workers + D1, cookie sessions **30d+**. Sign in only at
  commit or league join; builder and countdown are public.
- **iOS has three isolated browser contexts** (in-app WebViews, SFSafariView
  from iMessage/WhatsApp, and the Home Screen PWA) with separate cookies and
  storage. Therefore: detect embedded WebViews by UA and show "Open in Safari
  to play" + copy-link (they can't complete Google OAuth: `disallowed_
  useragent`); encode `?join=CODE` and a bracket hash in Better Auth's
  `callbackURL`, never rely on localStorage alone; persist the bracket
  server-side the instant sign-in completes; treat "sign in again" after
  install as a normal two-tap event. Do the sign-in in the Safari tab; the
  install card comes after.
- **Profile:** display name (prefilled, editable), avatar = provider URL.
  Location later. Blocklist on names; admin can hide from global; commissioner
  can remove from a league.
- **Push** (Web Push; reuse phishpicker's VAPID keys). Launch = one toggle,
  level **Set breaks**: morning-of if not committed, T−60 empties nudge,
  set-break summary ("S1 done: you 26, Phish 21 · 2nd in Couch Tour Crew"),
  recap. *Quiet* and *Every hit* levels later; "Every hit" needs the paid
  subrequest budget. Title carries the outcome via emoji (iOS ignores icons).
  Pushes originate from the show coordinator via a **push outbox** drained in
  chunks of ≤ 40 per alarm, dedup key `(user, event_id)`.

## Architecture

All Cloudflare. **Workers Paid ($5/mo)** — the free tier's 100k requests/day
and 100k DO requests/day die on the first show night from client polling alone
(100 users × 3 polls/min × 4.5h ≈ 81k). Everything else stays near zero.

- **Worker** running **Hono** (API; `/l/:code` and `/s/:date` served via
  `env.ASSETS.fetch(index.html)` + `HTMLRewriter` injecting OG tags) and
  serving a **Vite React PWA** as static assets (don't count against request
  limits). Not Next.js. Tailwind, vitest. Ported from phishpicker: `ScoreFeed`,
  `PullToRefresh`, `PushToggle` (fixed to surface the install path),
  `ServiceWorkerRegister`, `AddSongSheet` search. **Not** `ScoreHero` — wrong
  question and wrong split; the new hero is ME vs PHISH.
- **D1 via Drizzle** — system of record.
- **One Durable Object per show — the show coordinator.** Single writer with
  **all state in DO storage** (objects are evicted between alarms). Drives
  itself with `setAlarm`: phish.net poll, lock, consensus freeze, set-break
  push, close-out. Alarm handler idempotent (alarms retry on throw). **Cron
  only arms the day's DO** (every 5–15 min) plus daily jobs (morning push,
  provisional→final, post-final re-poll).
- **Live reads come from the DO**, with **Cache API** (`caches.default`,
  `s-maxage` 15–20s, per-colo, unmetered) in front so friends at one show
  share an origin hit. **No KV at launch** — it's eventually consistent (up to
  60s+ cross-colo) and boards would go backwards. Every live payload carries a
  monotonic `version`; the client discards anything older than shown. Clients
  poll every **60s** while live (phish.net's data changes at most every ~2
  min, so faster polling buys nothing), with "updated Ns ago" +
  pull-to-refresh. ~270 requests per user per show; the paid plan's 10M/month
  covers ~4,600 users polling every show of an 8-show month, and overage past
  that is $0.30 per million. If scale ever demands it, hibernating WebSockets
  on the show DO replace polling entirely (and are the same machinery league
  chat wants).
- **Live scores live in the DO** (one blob per show) and flush to D1 at set
  end and close-out — not per song (D1 row-write budget). Scoring CPU is a
  non-issue (100 brackets × 18 picks × 25 songs ≈ 45k comparisons).

### Data model (D1)

- `users` — id, google id, display name, avatar url, created
- `shows` — phish.net showid, date, venue id/name, city, tz, `scheduled_start`,
  `lock_at` (UTC), tour id/name, run id + night N/M, structure JSON, status
  (`upcoming · open · locked · live · provisional · final · postponed ·
  cancelled`)
- `show_bundles` — published artifacts per show, `(show, bundle_seq)`; last
  before lock = frozen PhishPicker bracket + the `top_k` consensus ties use
- `songs` — keyed on phish.net `songid`: name, all_time_plays, last_played,
  gap_shows
- `brackets` (user × show, picks JSON, pinned mask, committed_at, locked_at)
- `consensus_brackets` — per show, at lock
- `setlist_entries` — show, set, within-set position, songid (null → bustout
  placeholder name), occurrence#, first_seen_at
- `scores` — bracket × show: points, phish_points, tier counts, badges JSON;
  flushed at set end / close-out; idempotent from the setlist
- `leagues` · `league_members` (role, joined_at) · `season_standings`
  (materialized at close-out and on any post-final correction)
- `push_subscriptions` · `feed_events` (show-scoped, league-scopable later)

### Data flow

**NAS → cloud: publish, not serve.** `phishpicker publish <date>` POSTs a
signed bundle to `POST /ingest/bundle`: show meta (incl. `tour_name`,
`showid`, `venueid`), structure, model bracket, per-slot `top_k` (songid,
name, prob, plays, gap), catalog snapshot. Runs from the ingest-cron sidecar:
morning-of, hourly until lock. **Signing:** HMAC over `schema_version ·
key_id · timestamp · nonce · sha256(body)`; reject > 5 min skew; store recent
nonces; `timingSafeEqual`; per-show monotonic `bundle_seq` so a delayed retry
can't overwrite a newer bundle (upsert on `(show, bundle_seq)`). NAS outbound
only. NAS dead all day → previous bundle stands. **Note:** the local DB has no
Oct shows yet — publish needs a fresh ingest first.

**Live path — NAS not involved.** The DO polls `setlists/showid/{id}` (not
showdate — that endpoint returns all artists) **every 2 min** (phish.net caches
~5 min; 60s buys nothing and risks the key). Match by **`songid`** (duplicate
names exist: Gloria ×2, Let's Go ×2; placeholders get renamed after debuts);
name fallback only for ids absent from the snapshot → bustout placeholder.
Positions are show-monotonic and shift on insertions: **re-derive within-set
position every poll and diff the whole fingerprint** `(set, pos, songid)`;
feed events and pushes dedupe on `(songid, occurrence#)`, not position. Each
change → recompute all brackets + PhishPicker + consensus → DO state → cache
bust → outbox.

**Scoring in TypeScript**, guarded by **golden fixtures exported from
phishpicker** (`phishpicker export-fixtures`: Jul-12 and Jul-14 at minimum —
under the gap-based rare rule 122–15 and 24–39 — plus the other tour brackets). Drift = red
test.

### Phishpicker-side changes (this repo)

- `publish <date>` (bundle schema, HMAC, `bundle_seq`), `export-fixtures`.
- Ingest Oct shows; carry `tour_name`, `showid`, `venueid`, `gap` in bundles.
- Rare bonus → gap ≥ 50 in `scoring.py`; re-run the Jul-12/14 contract test.
- Structure per show type (3-set nights) if not already emitted.

## Testing

- Scoring: pure function; golden fixtures from phishpicker + synthetic
  fixtures for every exception rule. 100%.
- Coordinator: **replay Jul-12 and Jul-14** through the DO under Miniflare from
  recorded polling sequences incl. insertions and set-label flips; assert
  idempotent scores, one event per `(songid, occurrence#)`, one push per user
  per event, outbox chunking.
- Lock: edits at/after `lock_at` rejected; early-song lock tightening.
- Standings + tie-breaks: table-driven incl. missed shows, ties, cancelled
  shows, post-final corrections. 100%.
- Consensus: pinned-only, deterministic, frozen-bundle ties.
- Builder: sample-not-top-1, re-roll pinning, no-duplicate, swap mode,
  `callbackURL` round trip.
- Manual on a **physical iPhone from an iMessage link** (WebView detection,
  Safari OAuth, add-to-home-screen, push arrives) — this replaces Playwright
  at launch.

## Oct 2 scope (13 days) — what actually ships

**Spikes, in order, ~1 day each, on the paid plan:**
1. DO alarm loop polling phish.net + recompute + outbox, replaying Jul-12 /
   Jul-14 in Miniflare against the golden numbers.
2. Better Auth Google on Workers + D1 through the iPhone Safari → home-screen
   path.
3. Web Push from a Worker (`@block65/webcrypto-web-push` or `@pushforge/
   builder`) to a real iPhone.
4. HMAC `publish` from the NAS sidecar → `/ingest/bundle` → filled bracket
   rendered.

**Ships:** journey 1 end to end (builder, commit, Google sign-in, "You're in,"
lock, live ME vs PHISH + feed, recap with the PhishPicker reveal and the
series record); minimal leagues (create name-only, invite link on the builder,
per-show + this-tour board, remove member); push (one toggle, set breaks);
static rules page with attribution; provisional → final cron; admin:
`scheduled_start`, cancel, force-structure + re-score.

**Cut until mid-tour or later:** Apple sign-in; The Fans row (still computed);
level 3 entirely; run boards; explicit season scoping / join deadline / league
notes / podium share image; drag reorder; Quiet + Every-hit push levels;
"played last night" tag; profile location; postponed flow (admin-manual);
full `feed_events` history (a correction toast suffices); Playwright; KV.

## Deferred (post-tour)

- **Live next-song calls**: needs a trusted real-time source (phish.net's
  5-min cache makes anti-cheat impossible) and a live model worth playing.
- **League chat** — DO per league room + WebSockets; interleave with
  `feed_events`; commissioner delete + user report.
- Streaks/combos; "beat the picker" points; avatar uploads; email;
  best-N-of-M seasons; generated share images.

## Decisions (confirmed 2026-09-19)

1. **Workers Paid, $5/mo.** Free tier with 60s polling would survive ~350
   users on a show night; not worth a 429 at 9pm on opening night.
2. **Google-only sign-in at launch.** Apple after the tour ($99/yr program,
   self-signed client-secret JWT rotated ≤ 6 mo, name-only-on-first-consent,
   `form_post` cookie quirk).
3. **Rare bonus = gap ≥ 50**, changed in both scorers.
