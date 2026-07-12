# Phishpicker scoring game — design

**Status:** approved 2026-07-01 · revised 2026-07-01 after four expert reviews
(game-balance, architecture/correctness, Phish-domain, UX).

## Goal

Turn phishpicker from a predictor into a *game*: score how well the app
predicts a show, both before it starts and live as it unfolds, so watching the
predictions land becomes its own thrill. This is a **self-score for the app**
(the model's predictions), not a user-input picking game — no "enter your guess"
UI.

Two ways the app can "get a song right", mapped to two ledgers:

- **🔮 Foresight** — the model's full-setlist guess, locked before the show.
- **⚡ Live** — the next-song call, scored as the show unfolds.

## Core scoring model

**Every *actual* song is scored exactly once — best claim wins.** A song is
evaluated against both ledgers and banks the **larger** of the two (comparing
**base** values), attributed to that ledger. Never both (no double-dipping).
Because pre-show base values are higher than live base values, a song the app
*foresaw well* banks the bigger Foresight points; the Live ledger earns on songs
the pre-show bracket **missed or mis-placed**.

Worked example — bracket predicted Tweezer in Set 1, it played Set 2, and the
live model then called it as the next song:
- Foresight base: "played, wrong set" = 5
- Live base: "next-song exact" = 30
- → banks **30 (Live)**. Foresight still wins whenever it placed the song well
  (exact 40 > live base 30).

### The Foresight bracket is frozen at show start

The model's predictions change the instant a song is entered, so at show start
we **snapshot the pre-show forward-sim setlist** and store it (JSON) — that
frozen bracket is what Foresight scores against, untouched all night. Confirmed:
`build_preview` with zero entered songs produces a **deduped one-song-per-slot**
bracket (default 9/7/2 structure), so `slots[i].top_k[0]` per `(set, position)`
is directly freezable.

### "Exact slot" means (set, position-in-set) — NOT global index

Real set lengths diverge wildly from the predicted structure, so matching by a
global slot index makes exact/opener hits nearly unwinnable. Definitions:
- **Exact slot** = same `set_number` AND same position-within-set.
- **Right set, wrong position** = same `set_number`, different position.
- **Played somewhere** = played, different set.

## Point ladder

All values tunable; the **ordering** does the work.

| Ledger | Event | Points |
|---|---|---|
| 🔮 Foresight | predicted song played **somewhere** (wrong set) | 5 |
| 🔮 Foresight | predicted song, **right set**, wrong position | 15 |
| 🔮 Foresight | predicted song, **exact slot** (set + position) | 80 |
| 🔮 Foresight | exact slot **and it's a set opener** | **100** |
| ⚡ Live | **next-song call** exact (#1 pick = actual next), base | 30 (×combo) |
| ⚡ Live | **look-ahead** correct | 0 — `🔭 called it early` badge only |

> **Retune (2026-07-12):** exact 40→**80**, opener 60→**100**. Measured on the
> first three scored shows (54 bracket picks): a *right-set* hit turned out about
> as likely as a *somewhere* hit yet already paid 3×, while an *exact* slot was
> ~6× rarer than right-set but paid only 2.7× — underpriced. 80/100 push the
> scarce events toward fair odds and roughly double Foresight's share of the
> combined total, which was running ~27% (Live is far higher-frequency per
> attempt). Live base (30) and the combo cap are unchanged; the top live call
> (30×2 = 60) now sits strictly below the opener prize.

**Set-opener bonus (60)** applies to: **S1.1, S2.1, festival Set-3/Set-4
openers, and the first encore song (`E`)**. First songs of a **second/third
encore (`E2`/`E3`) score as exact-slot 40**, not 60 (the 2nd/3rd encore opener
isn't the hard, showy call the bonus is meant to reward).

**Look-ahead is a badge, not points.** When a song plays that the app had
correctly placed 2+ slots ahead, show a `🔭 called it early` beat in the feed
(0 pts). We have the data for free (see storage) — this keeps the delight
without the near-dead points and the anti-double-count rule. Real look-ahead
scoring can return in v2.

### Streak / combo multiplier (caps at ×2)

Consecutive **correct next-song calls** build a combo:

| In a row | Multiplier | Live next-song value |
|---|---|---|
| 1st | ×1 | 30 |
| 2nd | ×1.5 | 45 |
| 3rd+ | ×2 (cap) | 60 |

Cap ×2 keeps the top live call (60) below the opener prize (100) — never above —
and stops one hot run from swamping the total.

**Combo rules (decoupled from the ledger):**
- The streak counts **consecutive correct #1 next-song calls**, *regardless of
  which ledger banks the song* — the intuitive "how many in a row."
- A next-song **miss resets it to 0**. A **bustout is a missed next-song call**,
  so it banks 0 *and* breaks the streak (state this explicitly to players).
- The **multiplier applies only to points banked in the Live ledger.** A song
  that banks Foresight advances the streak (meter climbs) but isn't multiplied —
  it already earned the larger Foresight points. Best-claim always compares
  **base** values, so the multiplier never lets Live steal a well-foreseen song.
- To avoid a glowing-but-empty meter on a foreseen call, the UI shows a
  **`✓ foreseen`** beat and frames the meter as "banking toward the next live
  catch." (Playtest this interaction.)

## Architecture: one pure engine, capture-don't-recompute

A `scoring.py` module is a **pure function** of
`(frozen bracket JSON, ordered actual setlist, captured live-prediction JSON)`
→ per-song attributions, ledger totals, streak timeline. The **live view** and
the **post-show scorecard** both call it — same math, so they can never
disagree, and it's fully unit-testable (TDD).

**Capture, don't recompute.** The model is run **once per slot, live**; its
output is captured as JSON and *never re-run for scoring*. This dissolves three
architectural hazards:
- **Nondeterministic predict tiebreak** → irrelevant to scoring (we score the
  captured list, not a recompute). (Still worth adding a deterministic tiebreak
  in `predict.py` so the *live call itself* is stable.)
- **Candidate-pool drift** (bustout placeholder inserts mid-show) → irrelevant,
  no recompute.
- **Self-heal on correction** → trivial: a phish.net correction is just another
  entry that appends a fresh snapshot + updates the actual setlist; re-run the
  pure scoring function over the new JSON. We score the app's **actual captured
  live calls** — what it really showed you — which is more honest and keeps the
  live view and recap telling the same story.

### Storage (denormalized JSON in `live.db`)

One row per live show — held in memory during the show, flushed to DB:

```
live_score_state(
  show_id     TEXT,        -- live_show uuid
  model_sha   TEXT,        -- refuse to mix shas in one scorecard
  frozen_bracket  JSON,    -- the pre-show predicted setlist
  snapshots       JSON,    -- append the full remaining-setlist prediction
                           --   each time an entry changes it
  ledger_cache    JSON     -- optional running totals for fast reads
)
```

A whole show is ~20-25 snapshots × ~20 slots ≈ **10-20 KB of JSON**. Trivial.
No normalized snapshot table, no schema-migration complexity.

### Wiring

1. **Freeze** — at first-song entry (or an explicit `/live/show/{id}/freeze`),
   run `build_preview` with zero entered songs and persist the per-`(set,
   position)` `top_k[0]` picks to `frozen_bracket`.
2. **Capture** — the sync loop already calls `predict_next_stateless`
   (`live_sync.py`) and discards all but the actual song's rank; instead,
   append the full remaining prediction to `snapshots` on every change (normal
   entry *or* correction).
3. **Score** — a **recompute-on-read `/live/show/{id}/score`** endpoint runs the
   pure engine over `live_songs` + `frozen_bracket` + `snapshots`. This avoids
   double-wiring scoring into both the manual `/live/song` and the phish.net
   sync write paths.

### Pre-existing bug to fix (blocks encores today)

`live_songs.set_number` CHECK allows only `('1','2','3','4','E')`, but phish.net
sync produces `'E2'`/`'E3'` and would **crash `append_song`** on any double
encore. Allow `E2`/`E3` (and emit them from the bracket structure) — required
regardless of scoring, since the game leans on encores.

## Surfaces

### Live scoreboard (the emotional centerpiece)

The engine emits structured scoring events so the UI can be as juicy as we want
without touching scoring logic.

- **One hero total** (Foresight + Live combined) that *punches* on each hit; the
  two-ledger split is a smaller secondary readout (`🔮 210 · ⚡ 135`). The split
  is a footnote mid-show and the star of the recap.
- **Every event states the claim it beat** so best-claim-wins is self-evident,
  not arbitrary: `Tweezer — ⚡ NEXT-SONG ✓ +30  (beat 🔮 wrong-set +5)`.
- **Ledger color identity**, used everywhere: Foresight = indigo (app accent) /
  crystal; Live = amber-or-cyan / lightning. Color is preattentive; labels alone
  aren't legible at show volume.
- **The next-song card flip is *the* moment to nail** — pending call sitting
  face-up with a subtle pulse → song entered → hit = satisfying snap + combo
  tick + points fly into total; miss = card deflates, meter drains. Everything
  else decorates this beat. Reuse the existing `HitRankIndicator` bullseye as
  the "called it" glyph.
- **Combo meter** understated at ×1, escalates hard at ×1.5 / ×2; the miss-reset
  drain should have weight.
- **`🎸 BUSTOUT` callout** framed as a *celebration* of a rare song (gold /
  special), never a sad "miss" — protects the app from feeling dumb when Phish
  is genuinely unpredictable.
- **First-event coach mark** (not a manual): the first scoring event of the
  night annotates itself once ("🔮 Foresight = the app's pre-show guess…"), plus
  a persistent framing header ("How well is the app calling tonight?").
- The **pre-show opener call** is surfaced prominently at show start — S1.1 can
  only ever bank Foresight (live starts after the opener), so make it feel
  special rather than shortchanged.

### Post-show scorecard

Same engine over the final setlist. Foresight breakdown, Live breakdown, streak
highlights, total, cross-show context, and a self-deprecating **"songs that beat
the app"** list (the bustouts/misses).

## Edge cases & rulings

1. **Soundcheck (`'S'`) rows** — filtered out entirely before scoring (both
   ledgers, live + post-show). Never predicted, never scored. (Today `'S'` sorts
   to slot 99+ and would create phantom trailing bustouts.)
2. **Bustouts / tour-debuts** — not in bracket or next-song call → **0 in both
   ledgers, no penalty**, but a bustout **breaks the streak** (it's a missed
   next-song call). Celebrated in the UI and listed in the recap.
3. **Sandwiches / true repeats** — "best occurrence, consumed once" applies only
   to an **identical `song_id`** played twice. Reprise-*named* songs (Tweezer /
   Tweezer Reprise, Mike's / Weekapaug) are **distinct `song_id`s**, scored
   independently. Because the live model can't re-predict an already-played
   song, a genuine repeat **scores 0 in Live** (honest).
4. **phish.net corrections** — engine is pure over captured JSON + setlist, so a
   correction just appends a snapshot + updates the setlist and we re-score. UI
   shows a **labeled** `↻ Corrected …` micro-event and counts the delta
   (never a silent point-yank); downward corrections are rare and always
   explained ("phish.net confirmed" = authority, not punishment).
5. **Unknown set boundaries mid-show** — live next-song + streak don't depend on
   set structure and fire immediately. Foresight set/opener refinements settle
   as structure is declared; the post-show scorecard (full structure known) is
   authoritative.
6. **Cross-show "best yet?"** — store each show's final total + breakdown.
   Headline = **raw total**; secondary = **points-per-song computed over
   predictable songs only** (exclude debuts/bustouts from the denominator so the
   fairness metric doesn't contradict rule #2). Full leaderboard/history
   deferred.

## Deferred (YAGNI for v1)

- User-input picking / multiplayer ("you vs the app").
- Full show-history browser and leaderboard.
- Look-ahead *scoring* (kept as a 0-pt badge in v1).
- Baseline-relative skill normalizer (vs a frequency model) — nice fairness
  upgrade, heavier than v1 needs.
- Sound design (part of the UI polish pass).

## Open implementation notes

- The **combo-on-a-foreseen-night** interaction (meter climbs, multiplier pays
  only on Live-banked songs) is the one rule to feel out in playtesting.
- Frozen bracket uses the default 9/7/2 structure pre-show, so exact/opener
  scoring is mildly biased toward shows matching that shape; degrades gracefully
  (exact → right-set → anywhere). Acceptable for v1.
- Stamp `model_sha` on the score state; if the model is reloaded mid-show,
  refuse to mix shas in one scorecard.
- Match the `_SET_ORDER` convention in `retro.py` / `slot_ranks.py` for slot
  ordering; do NOT reuse `retro.py` (it matches by song *name* and consumes JSON
  preview docs) — build `scoring.py` fresh on `song_id`s.
