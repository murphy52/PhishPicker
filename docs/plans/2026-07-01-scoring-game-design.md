# Phishpicker scoring game — design

**Status:** approved 2026-07-01

## Goal

Turn phishpicker from a predictor into a *game*: score how well the app
predicts a show, both before it starts and live as it unfolds, so watching
the predictions land becomes its own thrill. This is a **self-score for the
app** (the model's predictions), not a user-input picking game — no new
"enter your guess" UI.

There are two ways the app can "get a song right", and they map to two
scoring ledgers:

- **🔮 Foresight** — the model's full-setlist guess, locked before the show.
- **⚡ Live** — the next-song call (+ look-ahead), scored as the show unfolds.

## Core scoring model

**Every *actual* song is scored exactly once — best claim wins.** A song is
evaluated against both ledgers and banks the **larger** of the two, attributed
to that ledger. Never both (no double-dipping). Because pre-show point values
are higher than live values, a song the app *foresaw well* naturally banks the
bigger Foresight points; the Live ledger earns points on songs the pre-show
bracket **missed or mis-placed**.

Worked example — bracket predicted Tweezer in Set 1, it played Set 2, and the
live model then called it as the next song:
- Foresight claim: "played, wrong set" = 5
- Live claim: "next-song exact" = 30
- → banks **30 (Live)**. Pre-show still wins whenever it placed the song well
  (exact 40 > live 30).

### The Foresight bracket is frozen at show start

The model's predictions change the instant a song is entered. So at show start
we **snapshot the pre-show forward-sim setlist** and store it — that frozen
bracket is what Foresight scores against, untouched for the rest of the night.
The Live ledger, by contrast, re-predicts continuously.

## Point ladder

All values tunable; the **ordering** is what does the work.

| Ledger | Event | Points |
|---|---|---|
| 🔮 Foresight | predicted song played **somewhere** (wrong set) | 5 |
| 🔮 Foresight | predicted song, **right set**, wrong position | 15 |
| 🔮 Foresight | predicted song, **exact slot** | 40 |
| 🔮 Foresight | exact slot **and it's a set opener** (S1.1, S2.1, encore) | **60** |
| ⚡ Live | **next-song call** exact (#1 pick = actual next) | 30 |
| ⚡ Live | **look-ahead** hit (model had it right, 2+ slots out) | 8 |

Ordering guarantees:
- live next-song (30) **<** pre-show exact (40) → well-foreseen songs bank Foresight.
- live next-song (30) **>** pre-show right-set (15) / anywhere (5) → a pre-show
  near-miss the live model *corrects* banks the bigger Live points.
- opener (60) is the top prize — the hardest, showiest call.
- look-ahead (8) is a small "it saw that coming" garnish.

**Encore = opener** for the 60-pt bonus (first song of `E`; first `E2` song too).

### Streak / combo multiplier

Consecutive **exact next-song calls** build a combo that multiplies the *live
next-song* points:

| Streak | Multiplier | Next-song value |
|---|---|---|
| 1st hit | ×1 | 30 |
| 2nd in a row | ×1.5 | 45 |
| 3rd in a row | ×2 | 60 |
| 4th+ | ×3 (cap) | 90 |

A next-song **miss resets the streak to 0**. Only next-song calls build/break
it — Foresight and look-ahead don't touch the streak (keeps the combo about the
live "what's next?" tension).

## Architecture: one pure engine, two callers

A `scoring.py` module is a **pure function** of:
`(frozen bracket, ordered actual setlist, per-slot live prediction snapshots)`
→ per-song attributions, ledger totals, streak timeline.

- The **live view** calls it incrementally after each song.
- The **post-show scorecard** calls the *same* function over the final setlist.

Same math → live and recap can never disagree, and the engine is fully
unit-testable (TDD).

### Data flow

1. **Show start** → freeze the pre-show forward-sim setlist as the Foresight
   bracket; store it (in `live.db`, keyed by show).
2. **Each song revealed** (via `/live/song` entry or phish.net sync) →
   - engine computes the song's best claim: Foresight (in bracket?) vs Live
     next-song (was it the #1 pick in the snapshot from *one* song ago?) vs
     look-ahead (did the snapshot from *two* songs ago place it correctly?),
   - banks the max, updates the ledger + streak,
   - emits a **scoring event** (points, ledger, new streak/combo) for the UI.
3. **Show end** → finalize + save the scorecard; unlock cross-show comparison.

### Storage

- **Frozen bracket** per show (new store in `live.db`).
- **Live prediction snapshots** per slot — reuse/extend `slot_predictions_cache`.
  These make look-ahead answerable and the whole score reproducible.
- **Final scorecard** per show (total + ledger breakdown + streak highlights)
  for cross-show comparison.

## Surfaces

### Live scoreboard (the emotional centerpiece)

The engine emits structured scoring events so the UI can be as juicy as we want
without touching scoring logic. Aim for:
- a big running total that **punches** on each hit,
- a filling **combo/streak meter** that glows at ×2 / ×3,
- the pending **next-song call shown face-up** so you feel the suspense,
- an animated **event feed** (`Tweezer — NEXT-SONG ✓ +45  🔥×1.5`),
- a **live bustout callout** when a song the app never saw hits
  (`🎸 BUSTOUT — the app never saw it coming`).

The visual/animation work is its own focused effort (frontend-design skill),
*after* the plan is locked.

### Post-show scorecard

Same engine over the final setlist. Shows the Foresight breakdown, the Live
breakdown, streak highlights, the total, and cross-show context. Includes a
self-deprecating **"songs that beat the app"** list (the bustouts/misses).

## Edge cases & rulings

1. **Bustouts / tour-debuts** — not in the bracket *or* the next-song call →
   **0 in both ledgers**. Honest (bustouts are unpredictable). No penalty.
   Called out in the live UI and the recap ("songs that beat the app").
2. **Sandwiches / reprises** — a Foresight bracket pick is consumed **once**,
   matched to its *best* actual occurrence. Other occurrences of that song are
   then eligible for the Live ledger like any normal slot.
3. **phish.net corrections** — the engine is pure, so on reconcile we
   **recompute from the corrected setlist**; the score self-heals. UI shows a
   gentle "score adjusted" beat, not a jarring point-yank.
4. **Unknown set boundaries mid-show** — live next-song + streak don't depend
   on set structure and fire immediately. Only Foresight set/opener refinements
   need boundaries; those settle as structure is declared. The post-show
   scorecard (full structure known) is authoritative.
5. **Cross-show "best yet?"** — store each show's final total + breakdown.
   Headline = **raw total**; secondary = **points-per-song** (fairer across
   shows of different length). Full leaderboard/history deferred.

## Deferred (YAGNI for v1)

- User-input picking / multiplayer ("you vs the app", friends compete).
- Full show-history browser and leaderboard.
- Streak flavors beyond the base multiplier.
- Sound design (nice-to-have during the UI pass).

## Open implementation notes

- Verify the forward-sim preview produces a **deduped** one-song-per-slot
  bracket (walks slot-by-slot removing played/predicted songs). Confirm before
  relying on it as the frozen bracket.
- Pin down the exact **look-ahead anti-double-count rule**: a song earns
  look-ahead at most once, credited to the snapshot where it was first placed
  correctly 2+ slots out, and only if not better-claimed.
- Decide whether the live scoreboard is a new route or folds into the existing
  live-show page.
