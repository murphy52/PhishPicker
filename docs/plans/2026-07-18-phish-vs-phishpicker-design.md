# Phish vs. PhishPicker — design

**Status:** designed (2026-07-18), approved. Not yet implemented.

A second scoring lens on the same live show: instead of "how well did the model
predict the show," it asks "how much did the band outsmart the model tonight."
The band earns points for playing songs the model didn't foresee; the model
earns points for the songs it placed. Watch the tug-of-war unfold live and root
for either side.

## Origin & the empirical work behind it

Sparked by the contrast between Jul 12 (foresight 390 — felt like magic) and Jul
14 (foresight 20 — the band clearly deviated). The intuition: a game that
rewards the band for surprising the model.

Two findings from the tour data shaped the design, and both are worth keeping in
mind if we ever revisit it:

1. **Do NOT build this on the live/next-song prediction.** Measured on the tour:
   the current model's next-song #1 is near-constant per set (it called
   "Sparkle"/"Poor Heart" every slot regardless of context) and essentially
   never lands #1. Under any strictness, the band "wins" ~90–100% every night,
   and it does NOT separate the magic nights from the weird ones. The frozen-vs-
   live-prior distinction is also moot: the model is nearly context-insensitive
   (median rank gap of 2 between the two priors).

2. **The frozen foresight bracket DOES discriminate**, cleanly, and it's what
   felt like magic. Scored against prod's real frozen brackets (all made by the
   same current model `f508a59d` — there was no model regression; an earlier
   local repro was just broken on stale data):

   | Show | exact | right-set | somewhere | **band %** |
   |------|-------|-----------|-----------|-----------|
   | Jul 7  | 0%  | 6%  | 11% | 83% |
   | Jul 8  | 0%  | 19% | 12% | 69% |
   | Jul 10 | 0%  | 19% | 12% | 69% |
   | Jul 11 | 0%  | 18% | 12% | 71% |
   | **Jul 12** | 13% | 53% | 0%  | **33%** |
   | **Jul 14** | 0%  | 0%  | 27% | **73%** |
   | Jul 15 | 7%  | 13% | 0%  | 80% |

   Jul 12 is the standout picker night; Jul 14 tips to the band. The model's
   real skill is "right song, right set, wrong slot" (the right-set column), not
   exact placement.

So the game inverts the **frozen foresight bracket**, which is also — by
definition — frozen pre-show, making it the fair, non-peeking version with no
live-updating variant to design around.

## Fairness: one calibrated axis, both sides graded

Not two forecasters competing — one forecaster (the model) vs. reality (what the
band plays), like scoring a weather forecaster against the weather. Every played
song sits on a single axis (how well the frozen bracket placed it) and scores for
exactly one side. Fairness comes from **calibration, not symmetry of activity**:
raw, the band wins ~68% of song-events tour-wide, so per-hit magnitudes must be
weighted to compensate — otherwise the band runs away every night.

**We calibrated against the 8 real tour brackets** rather than guessing. The
shipped constants (see Scoring model) produce a points ratio of 0.87 band:picker
and the model winning **3 of 8 nights** — a genuine coin, with the model a *mild
underdog*: it loses slightly more often than it wins, but not by much, and it has
rare blowout nights (Jul 12: 112–19). The per-show arc under these constants:

| Show | PhishPicker | Phish | leader |
|------|-------------|-------|--------|
| Jul 7  | 22 | 47 | Phish |
| Jul 8  | 42 | 37 | Picker |
| Jul 10 | 42 | 35 | Picker |
| Jul 11 | 42 | 42 | tie |
| Jul 12 | 112 | 19 | **Picker (blowout)** |
| Jul 14 | 24 | 35 | Phish |
| Jul 15 | 36 | 40 | Phish |
| Jul 17 | 26 | 46 | Phish |

So the personality — reconciling what earlier drafts stated inconsistently — is
**a fair coin in which the model is a mild underdog with rare magic nights.** Not
"usually loses" (that was the mis-tuned version where the band won 7 of 8); a real
back-and-forth. Constants stay tunable after live use, but they *start* calibrated,
not backwards.

## Scoring model

Per played song, from the frozen bracket's placement (the existing foresight
tiers via `score_foresight` — each actual song is claimed by at most one bracket
pick, consume-once):

- **PhishPicker points** (song was placed), calibrated tiers:
  `opener 20 · exact 16 · right-set 10 · somewhere 6`.
- **Phish points** (song absent from the bracket): `base 3` plus a rarity bonus:
  `+6` for a bustout placeholder (a song not in the local catalog, inserted at
  ingest), `+2` for a deep cut (fewer than 50 all-time plays). Note: a genuine
  catalog bustout — a known song unplayed for years — has a normal id and lands
  in the deep-cut (+2) branch, not the +6 branch; that's a coverage nuance, not a
  bug, and can be refined later.

These magnitudes come from calibrating against the 8 real tour brackets (ratio
0.87, model wins 3/8 — see the arc above), not from guesses. They remain tunable
after live use.

**Repeated songs:** `score_foresight` is consume-once, so a song played twice
against a single bracket pick scores PICKER for the first occurrence and PHISH
(with its rarity bonus) for the second. The model can thus be both credited and
debited for the same song — defensible ("each play is an event"), but it will
read oddly for Tweezer → Tweezer Reprise (related: the unresolved reprise-
dependency issue). Accepted for v1; flagged so it's a decision, not an accident.

## Data flow

The live score endpoint already returns per-song `attributions` with the tier
(`exact`/`right_set`/`somewhere`/`absent`), so the VS tally is mostly a re-read
of data already computed on each song entry. The only new backend piece is a
per-song **surprise weight** for absent songs, derived from existing rarity
stats. Emit a small `versus` block inside the existing score payload — **no extra
network round-trip during the show.**

## Frontend

- **`VersusBoard`** — a tug-of-war bar (Phish ↔ PhishPicker) plus the played
  songs annotated with which side scored each and why.
- **`LiveViewToggle`** — a two-segment `Picks | VS` control pinned just above the
  persistent `AddSongSheet`, in the thumb-reachable zone so views flip without
  moving your hand. Client-side state persisted to `localStorage` so it survives
  a mid-show reload.
- The main page swaps only the `<main>` display region on toggle; `PlayedStrip`
  and `AddSongSheet` stay shared and persistent. The existing Picks view
  (`FullPreview` + `ScoreTeaser`) is untouched.

Both scoreboards run off the same entered songs — one entry updates both.

## Testing

- Backend: unit tests for tier→picker points and rarity→band points; **golden
  tests on the tour** asserting Jul 12 comes out picker-dominant and Jul 14
  band-dominant.
- Frontend: component tests for the toggle (switch + `localStorage` persistence)
  and `VersusBoard` rendering both sides.

## Out of scope for v1 (YAGNI)

No VS history page, no VS leaderboard, no VS push notifications, no live-updating
variant. Just the live view + toggle. These earn their way in later, if at all.
