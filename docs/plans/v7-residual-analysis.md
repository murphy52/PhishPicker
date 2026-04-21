# v7 residual misses — analysis

**Question:** v7 lifted Top-5 from 14.5% to 21.2% but still misses on
specific slots. Can any be made tractable, or are they fundamentally
outside what setlist data can predict?

**Answer:** Of the three diagnostic miss categories, two are unfixable
from setlist patterns alone (bustouts and surprise-covers). The third —
set-2 closers — is potentially tractable with one new feature, but the
expected lift is moderate and we're holding feature changes to let v7
breathe in production. Recommendation deferred to v9.

## Categorization of v7 misses on 4/18 Sphere

| Slot | Actual | Rank | Category | Tractable? |
|---|---|---|---|---|
| 4 | Colonel Forbin's Ascent | #102 | Bustout | ❌ no |
| 7 | Walk Away (Joe Walsh sit-in) | #18 | Guest cover | ❌ no |
| 14 | Run Like an Antelope | #92 | **Set-2 closer** | 🟡 maybe |
| 15 | I Am the Walrus | #102 | Rare cover | ❌ no |

## Category 1: Bustouts — Forbin's Ascent (#102)

```
Last 10 Forbin's plays:   2026-04-18 ← 4/18 Sphere
                          2023-12-31  (2.3 year gap!)
                          2021-08-31
                          2017-07-30
                          2015-08-09
                          2013-12-31  ...
Total plays ever: 130
```

A 2.3-year gap counts as a textbook bustout. The model's `bustout_score`
(gain ~3K in v7) does flag long-gap candidates, but with hundreds of
"could be a bustout" candidates and no signal that says "tonight
specifically," this is fundamentally guesswork. **No feature fix is
likely to help.**

## Category 2: Surprise covers — Walk Away, I Am the Walrus

```
Walrus plays (last 10):   2026-04-18 set E pos 15
                          2025-07-22 set 1 pos 9
                          2025-07-12 set 2 pos 16
                          2023-10-11 set 2 pos 14
                          ... irregular positions across years
                          (10 plays in 16 years)
```

- **Walk Away**: triggered by Joe Walsh sitting in. External information.
- **Walrus**: 10 plays since 2010 in essentially random positions. No
  role pattern to learn from.

These are the misses you tell your friend about — a Phish concert is a
Phish concert because of these moments. **Can't be predicted from setlist
data alone.** Would require external signals (audience, special-occasion
flags, etc.) that we don't have.

## Category 3: Set-2 closers — Antelope (#92)

This is the only category with a tractable hypothesis.

### What the data says

```
Antelope:                Total plays: 508
                         As set-2 closer: 98 (19% of plays)
                         In encore: 32

Top set-2 closers (historical):
   98 × Run Like an Antelope
   98 × Slave to the Traffic Light
   98 × You Enjoy Myself
   88 × Cavern, Harry Hood
   ...
```

Antelope is **tied for the most-frequent set-2 closer in Phish's history**.
The pattern is real and strong.

### Why v7 missed it

```
Set-2 length distribution (last 200 shows):
   4 songs:   6 shows
   5 songs:  15 shows
   6 songs:  39 shows  ← 4/18 was a 6-song set 2
   7 songs:  64 shows  ← modal
   8 songs:  46 shows
   9+:       30 shows
```

For slot 14 (Antelope), v7's features said:
- `current_set` = 2  (correct)
- `is_set2` = 1  (correct)
- `is_first_in_set` = 0  (correct)
- `set_position` = 14  (global slot, not informative about set-2 progression)
- `closer_score` = high (correct — Antelope is a known closer)

What's *missing*: an explicit "we're approaching the end of the current set"
signal. The model has no way to know we're 6 songs into a typical 6–8 song
set 2 — the threshold where `closer_score` should dominate.

### Proposed feature for v9 (deferred)

**`slots_into_current_set`** — integer, 1-indexed position within the
current set. At inference time, derive from `(played_songs, current_set)`
by counting trailing songs that were also in `current_set`. The caller
already tracks set transitions for `prev_set_number`, so the data is
available with minimal plumbing.

**Expected behavior:** LightGBM learns interactions like
`(slots_into_current_set ≥ 5) AND (closer_score > 0.05) → boost`. The
"closer-territory" classification becomes a clean tree split rather than
something that has to be encoded indirectly via global slot number.

**Why this isn't urgent:**
- Top-5 is already 21.2%; further per-slot gains have diminishing return
- v7 needs production-soak time before we change anything
- Feature add + 3.5h retrain + deploy = expensive vs current uncertainty
  about lift (could be small)

### Why not tackle now

User explicitly said hold v8 cleanup until v7 is observed. v9 (with
new features) follows from v8. Order discipline matters more than
chasing an estimated +1pp Top-5.

## Honest summary

v7 is at the "good" end of what setlist-only data can produce. The
remaining ~80% of misses fall into:

- **Genuinely unpredictable** (bustouts, guests, rare covers): structurally
  outside model scope
- **Modestly tractable** (set-2 closers): could move 1–2pp with a
  `slots_into_current_set` feature, but worth deferring until v7 has
  baseline production data

Anything ambitious from here probably requires *external* signals
(announcements, social-media mentions, who's-in-the-audience data). That's
a different project, not a feature.
