# Phish vs Fans vs PhishPicker — design

**Status:** approved 2026-09-19. Separate project; this doc seeds the new repo
and stays here as the record of how it relates to phishpicker.

## What it is

A public PWA where Phish fans predict tonight's setlist as a bracket and score
points against the band. Three sides play every show:

- **Phish** scores when they play what nobody predicted. The more they deviate,
  the more they score. If Phish wins, everyone wins — fans love to be surprised.
- **PhishPicker** is the model's frozen bracket, scored exactly like a fan's.
  It represents "Phish being predictable."
- **Fans** — each fan individually, and collectively as **The Fans**, a
  consensus bracket.

Phishpicker (this repo) stays private and single-user: it trains locally, runs
on the NAS, and *publishes* artifacts to the game. It never serves the game
live.

## Principles

- **One goal at level zero.** *Pick tonight's setlist. Every song you call is a
  point for you. Every song you don't is a point for Phish. Beat Phish.*
- **Progressive disclosure.** Leagues are the first social layer, not the first
  goal — most launch users won't be in one. PhishPicker and The Fans are
  revealed one tap deeper. The best moment in the game is learning the
  builder's "suggestions" came from an AI you just beat; it's earned, not
  explained up front.
- **User journeys drive every screen** (below). Journeys 1 and 5 are the launch.
- **Symmetric fairness.** Every bracket is built on the identical published
  shape and scored by the identical pure function. Structure surprises never
  advantage anyone; they shift points toward Phish.
- **UX first, style later.** All color/type/spacing/radius are design tokens
  (CSS variables → Tailwind theme) with semantic names (`surface`,
  `accent-phish`, `accent-fans`, `accent-picker`). Components never use raw
  values. Build on a plain neutral token set; polish is a token swap plus
  motion/iconography, not a restructure. The only early visual decision is
  that the three sides have distinct color identities (legibility), and even
  those hues are tokens.

## User journeys

1. **Stranger, show tonight** (launch-critical). Link → landing *is* the pick
   screen (public, already auto-filled) → tinker → "Play this bracket" →
   Google/Apple sign-in (bracket rides through the redirect) → confirm screen:
   goal sentence, lock countdown, notification opt-in. Under 2 minutes.
2. **Stranger, no show soon.** Next show + countdown, sign in, "we'll ping you
   the morning of." Optionally browse the last show's scoreboard as a demo.
3. **Returning solo player, show day.** Morning push → picks → lock → live →
   recap push → recap.
4. **League creator.** Create (name only) → share link → watch friends appear.
5. **Invited friend.** Invite link → league page as landing → sign in
   auto-joins → journey 1.
6. **Live show.** Hero score ticking, rank moving, feed beats, one tap to level 2.
7. **Morning after.** Recap: beat Phish? beat PhishPicker? league finish, tour
   standings.
8. **Explorer.** Everything at level 3 — findable, never forced.

### Disclosure ladder

| level | who | what |
|---|---|---|
| 0 | everyone, first screen | make picks (auto-fill, tap-to-swap, search); goal sentence; lock countdown |
| 1 | after lock / live | Me vs Phish hero number; league standings if in one; live feed |
| 2 | one tap on the scoreboard | PhishPicker and The Fans rows: "also playing tonight" |
| 3 | explorer | tour/all-time boards, profile stats & badges, consensus detail, "show odds" toggle |

## Game rules

**Entries.** One bracket per **user × show** (never per league — see
invariant below). Shape is the published structure for that show (default
S1×9, S2×7, E×2; festivals/NYE published with their real set count). Editable
until **lock = scheduled showtime in venue tz**. No entries after lock. Skipping
shows is fine.

**Scoring** — VS-calibrated constants from
`2026-07-18-phish-vs-phishpicker-design.md`, identical for every fan bracket,
PhishPicker, and The Fans. Consume-once: each played song is claimed by at most
one pick.

| tier | pts |
|---|---|
| set opener (S1.1, S2.1, S3.1, E.1) | 20 |
| exact slot (set + position) | 16 |
| right set, wrong slot | 10 |
| played, wrong set | 6 |

**Phish**, against a given bracket, scores every played song absent from it:
base 3, +6 bustout placeholder (song not in catalog), +2 deep cut (<50
all-time plays). Repeats: first play claimed by the pick, second goes to Phish.
Soundcheck rows ignored. Phish's score is therefore *relative to an opponent*;
its headline number is vs PhishPicker (the objective "how surprising was
tonight").

No streaks/combos in v1. No "beat the picker" points: a correct pick the model
missed earns a **🎯 upset** badge, 0 pts.

**The Fans (consensus).** Most-picked song per slot across all locked entries,
ties broken by model probability. Computed once at lock, frozen, scored like
any bracket. Empty slots don't count toward consensus. If everyone auto-fills,
consensus ≈ PhishPicker; the crowd's edge only appears when people deviate on
purpose — that's the point.

**Boards.** Per show, three lenses: **Global three-way** (Phish vs The Fans vs
PhishPicker), **Mine** (Me vs Phish vs PhishPicker, plus "you beat N% of
fans"), **League** (members ranked; PhishPicker and The Fans shown as reference
rows, not ranked). Running boards per **show / run / tour leg / all-time**.
Profile stats: nights beat PhishPicker, nights beat Phish, best show.

### Structure exceptions (all on the public rules page)

- **Set length differs** (every show): nothing thrown out. Picks beyond the
  actual set length can't be exact but still score right-set/somewhere. Extra
  actual songs go to Phish unless someone had them.
- **Fewer sets than the shape** (rain delay → one long set): predicted sets are
  **joined end-to-end** and scored as one (S1 picks = positions 1–9, S2 picks =
  10–16). A remap before scoring, not a new scorer. A missing encore alone
  needs no rule.
- **More sets than the shape** (surprise S3): S3 songs score *somewhere* (6)
  for anyone who had them, Phish otherwise. No remap — a surprise set *is*
  Phish being unpredictable.
- **Late start:** lock is scheduled start; nothing changes.
- **Postponed:** show record moves, brackets carry over, editing reopens until
  the new lock, everyone is told.
- **Cancelled:** voided — no scores, no Phish points, dropped from every
  season's "N of M shows."
- **Weird data:** admin can force a show's structure and re-score; the re-score
  surfaces as a labeled correction event.

### Provisional → Final

Close-out on quiescence (ported from phishpicker `close_out`) → show is
**provisional**, recap push. Cron promotes to **final** 24h later. Any
phish.net delta in between re-scores and emits a labeled correction event
(never a silent point change). A season is final 24h after its last show.

## Leagues

- Anyone creates one (name only). Join by invite code/link. Unlimited members;
  a user can be in many. Global board = "everyone."
- **Invariant:** brackets are user × show. Leagues never own brackets; a
  league season is a scope (which shows) + a roster (which users), and
  standings are computed over `scores` for that intersection. One bracket
  counts in every league you're in. Do not add `league_id` to `brackets`.
  Standings UI must never imply "your bracket for this league"; the builder is
  reached from the show, not from a league.
- **Seasons:** scope = single show / run / tour leg / custom date range, with a
  listed schedule ("Fall 2026 — 12 shows — ends Oct 31"). Run and tour
  boundaries come from published show meta.
- **Commissioner** (creator): close joining or set a join deadline, remove
  members, see who joined when, edit league notes.
- **League notes:** free-text, pinned at the top of the league page. Rendered
  verbatim, never parsed. This is where a league writes whatever rules it
  wants among itself. The app has no wagering features, holds no funds, and
  says so in its terms.
- **Indisputable results:** published deterministic tie-breaks (total points →
  nights beat Phish → exact-slot hits → earliest-locked bracket); podium
  (1st/2nd/3rd) explicitly called out; nightly league winner callout; missed
  shows score 0 and standings show "8 of 9 shows"; after lock every member's
  bracket is visible to the league with its lock timestamp.
- **Share card:** final standings (podium + season name) as a shareable
  link/image with OG tags for group chats.

## Bracket builder

- **Always start complete.** First open → bracket already auto-filled from the
  model's per-slot `top_k`. The first action is *react*, never *fill*.
- **Auto-fill / re-roll:** per slot, sample from candidates within a
  probability band of the slot's top pick (≥ ~40% of top, cap ~6), weighted by
  probability; **no song twice in a bracket** (reprise pairs are distinct ids).
  Hand-picked slots are **pinned** and survive re-rolls; slots can be re-rolled
  individually. Openers draw from a slightly wider band.
- **Tap a slot → picker sheet:** 6–8 suggested chips with **gap** ("last
  played 14 shows ago") and a subtle likelihood bar (no percentages at level 0;
  "show odds" is a level-3 toggle); search over the whole catalog (fuse.js,
  ported from `AddSongSheet`); "played last night" tag on multi-night runs
  (warning, not block).
- **Reorder:** drag within a set (dnd-kit) + tap-two-slots-to-swap fallback.
- **Commit:** one button, **"Play this bracket."** The entry exists from that
  moment; edits auto-save (debounced, server-side) until lock. Confirm screen =
  goal sentence + lock countdown + notification opt-in.
- **Partial brackets:** slots can be cleared after commit; empty slots score 0
  and are excluded from consensus. T−60 push nudges empties. Never auto-fill on
  someone's behalf after commit.

## Sign-in, identity, notifications

- **Auth:** Better Auth, Google + Apple, cookie sessions, D1 adapter. Sign in
  only when it matters: next show, countdown, and the builder are public;
  "Play this bracket" and league joins trigger sign-in. OAuth naturally limits
  most people to one or two entries; duplicates aren't worth fighting — it's
  for fun.
- **Profile:** display name (prefilled, editable), optional location, avatar =
  provider URL (no uploads in v1 → no R2, no image moderation).
- **Moderation (v1):** display-name blocklist; admin can hide a user from the
  global board; commissioner can remove from a league. Sufficient until there's
  a comment feature.
- **Push** (Web Push, opt-in after first commit), three levels, default bold:
  *Quiet* (recap only) · ***Set breaks*** (morning-of if not committed, T−60
  empties nudge, set-break summaries, recap) · *Every hit*. Title carries the
  outcome via emoji (iOS ignores per-notification icons). Pushes originate from
  the show coordinator so they're ordered and de-duplicated by construction.

## Architecture

All Cloudflare, free tier until it isn't. Cost is the constraint: no revenue.

- **Worker** running **Hono** (API + OG-tag routes for share/invite links) and
  serving a **Vite React PWA** as static assets. Not Next.js: no SSR need
  beyond OG tags, and OpenNext-on-Workers adds friction for no gain. Tailwind,
  vitest. Existing phishpicker components port nearly unchanged: `ScoreHero`,
  `ScoreFeed`, `PullToRefresh`, `PushToggle`, `ServiceWorkerRegister`,
  `AddSongSheet` search.
- **D1** via **Drizzle** — system of record.
- **KV** — hot read cache: current show state, scoreboards. At 8pm every
  client read is a KV hit.
- **One Durable Object per show — the show coordinator.** Single writer: owns
  the live setlist, runs scoring on each new song, batches D1 writes,
  refreshes KV, fires pushes. Makes "score every bracket, once, in order"
  trivially correct (the lesson of the July sync-reconcile bug, built in).
- **Cron Triggers** — wake the coordinator in the show window; morning-of push;
  provisional→final promotion.
- Clients poll the KV-backed endpoint ~every 20s while live. No WebSockets in v1.

### Data model (D1)

- `users` — id, provider ids, display name, location, avatar url, created
- `shows` — date, venue, city, tz, scheduled start, tour, run id + night N/M,
  structure JSON, status (`upcoming · open · locked · live · provisional ·
  final · postponed · cancelled`)
- `show_bundles` — published model artifacts per show, versioned; last before
  lock = frozen PhishPicker bracket
- `songs` — catalog snapshot: id, name, all_time_plays, last_played
- `brackets` (user × show, locked_at) · `bracket_picks` (set, position, song_id)
- `consensus_brackets` — one per show, computed at lock
- `setlist_entries` — show, set, position, song_id (null → bustout placeholder
  name), source, seen_at
- `scores` — bracket × show: points, phish_points, tier counts, badges JSON;
  recomputed idempotently from setlist
- `leagues` · `league_members` (role, joined_at) · `league_seasons` (scope
  type + bounds, join deadline, notes, status) · `season_standings`
  (materialized on each close-out)
- `push_subscriptions` · `feed_events` (per show, league-scopable later)

### Data flow

**NAS → cloud: publish, not serve.** New `phishpicker publish <date>` POSTs an
HMAC-signed bundle to `POST /ingest/bundle`: show meta, structure, model
bracket, per-slot `top_k` (song, prob, plays, gap), catalog snapshot. Runs from
the existing ingest-cron sidecar: morning-of, then hourly until lock (the model
shifts as the previous night ingests); the last bundle before lock is the
frozen PhishPicker entry. NAS dead all day → previous bundle stands; the game
runs on a slightly stale model.

**Live path — NAS not involved.** From T−15 the coordinator polls phish.net's
setlist endpoint every 60s. Name → `songs.id`; unknown → bustout placeholder
(the +6 case). Each new entry → score all brackets + consensus + PhishPicker →
`scores`, `feed_events` → KV → pushes.

**Scoring in TypeScript**, guarded by **golden fixtures exported from
phishpicker** (`phishpicker export-fixtures`: real tour brackets + setlists +
expected per-tier results, JSON in both repos). Drift = red test, not a league
dispute.

### Phishpicker-side changes (this repo)

- `publish <date>` command + bundle schema + HMAC secret in `.env`.
- `export-fixtures` command.
- Structure per show type (festival/NYE 3-set) if not already emitted.

## Testing

- Scoring: pure function; golden fixtures from phishpicker + synthetic fixtures
  for every exception rule (merged sets, surprise S3, repeats, bustout
  placeholder, correction re-score). 100% coverage.
- Coordinator: replay tests through the DO with Miniflare over recorded
  phish.net polling sequences incl. out-of-order corrections; assert
  idempotent scores, one feed event per beat, one push per user per event.
- Standings + tie-breaks: table-driven, incl. missed shows, late joiners,
  cancelled shows, provisional→final flips. 100%.
- Consensus: deterministic; ties → model probability.
- Builder: re-roll pinning, no-duplicate invariant, picker search, localStorage
  survival across the sign-in redirect.
- E2E (Playwright): journeys 1 and 5 only.

## Build order

1. **Spikes:** Web Push from Workers (WebCrypto VAPID lib; `web-push` won't
   run there), Better Auth Google + Apple on Workers, D1 + Drizzle + one DO
   round-trip.
2. Phishpicker: `publish` + HMAC endpoint contract, `export-fixtures`.
3. Scoring + standings in TS against fixtures. No UI.
4. Show ingest + coordinator + close-out; replay a past show end-to-end.
5. Builder + commit + sign-in (journey 1). First playable.
6. Live scoreboard + recap + push (journeys 3, 6, 7); levels 0–2.
7. Leagues: create/join/commissioner/notes/seasons/podium/share card (4, 5).
8. Level 3: run/tour/all-time boards, profile stats, badges, show odds, rules page.
9. Soft launch with friends on a real show night; then open signups.

## Deferred

- **Live next-song calls** (v2): needs a trusted real-time setlist source (anti-
  cheat vs phish.net lag) and a live model worth competing against (today's
  next-song call is near-constant per set). Timestamped picks + per-show
  event log leave room.
- **League chat** — live comment stream per league, Twitch-style. Same pattern
  as the show coordinator (DO per league room + WebSockets); `feed_events`
  interleaves beats and messages; needs commissioner delete + user report.
- Streaks/combos; "beat the picker" points; avatar uploads (R2); WebSockets;
  email; per-league season variants beyond scope (e.g. drop-lowest-N).

## Open questions to settle during implementation

- Exact auto-fill band and cap — playtest against real `top_k` distributions.
- Quiescence thresholds for close-out on Workers (port phishpicker's, then tune).
- Whether the morning-of bundle should ship the *inclusion* model's list as a
  level-3 "Likely Tonight" view. Nice, not v1.
