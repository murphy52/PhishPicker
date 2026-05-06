# Sphere 2026 — Forward-Sim Retrospective

Compares 7 forecast variants generated on Night 4 day against the actual setlists for Nights 4–9.

## Per-night set-level overlap

Of the songs each variant predicted for that night, how many were actually played that night.

| Variant | Night 4 | Night 5 | Night 6 | Night 7 | Night 8 | Night 9 | Total |
|---|---|---|---|---|---|---|---|
| greedy | 3/18 | 5/18 | 3/18 | 3/18 | 4/18 | 1/11 | 19/101 |
| paced-0.4 | 2/18 | 0/18 | 5/18 | 4/18 | 2/12 | 1/15 | 14/99 |
| paced-0.5 | 0/15 | 2/18 | 1/16 | 2/18 | 2/18 | 1/7 | 8/92 |
| paced-0.6 | 6/18 | 5/18 | 2/18 | 1/15 | 2/18 | 0/18 | 16/105 |
| paced-0.8 | 3/18 | 2/18 | 2/18 | 4/18 | 3/18 | 1/14 | 15/104 |
| paced-1.0 | 3/18 | 2/18 | 2/18 | 4/18 | 3/18 | 1/14 | 15/104 |
| assign | 4/18 | 1/18 | 4/18 | 1/18 | 6/18 | 2/18 | 18/108 |

## Per-night slot-exact match

Same song at the same (set, position) — strict positional accuracy.

| Variant | Night 4 | Night 5 | Night 6 | Night 7 | Night 8 | Night 9 | Total |
|---|---|---|---|---|---|---|---|
| greedy | 0/18 | 1/18 | 0/18 | 1/18 | 0/18 | 0/11 | 2/101 |
| paced-0.4 | 0/18 | 0/18 | 0/18 | 1/18 | 0/12 | 0/15 | 1/99 |
| paced-0.5 | 0/15 | 0/18 | 0/16 | 0/18 | 0/18 | 0/7 | 0/92 |
| paced-0.6 | 0/18 | 0/18 | 0/18 | 0/15 | 0/18 | 0/18 | 0/105 |
| paced-0.8 | 0/18 | 0/18 | 0/18 | 1/18 | 0/18 | 0/14 | 1/104 |
| paced-1.0 | 0/18 | 0/18 | 0/18 | 1/18 | 0/18 | 0/14 | 1/104 |
| assign | 0/18 | 0/18 | 0/18 | 0/18 | 0/18 | 0/18 | 0/108 |

## Residency-wide aggregates

- **pred_unique**: distinct songs the variant chose across all 6 nights
- **overlap**: of those, how many appeared somewhere in the residency
- **right_night**: of the overlap, how many were predicted on the night they actually happened

| Variant | pred_unique | overlap | right_night |
|---|---|---|---|
| greedy | 101 | 82 | 19 |
| paced-0.4 | 99 | 77 | 14 |
| paced-0.5 | 92 | 71 | 8 |
| paced-0.6 | 105 | 78 | 16 |
| paced-0.8 | 104 | 85 | 15 |
| paced-1.0 | 104 | 85 | 15 |
| assign | 108 | 80 | 18 |

_Total unique songs actually played across residency: **110**_

## Per-song catch table

One row per song actually played at the Sphere (Nights 4–9). Cells show the night each variant predicted that song (`N4 ✓` = right night, `—` = not predicted).

| Song | Actual | greedy | paced-0.4 | paced-0.5 | paced-0.6 | paced-0.8 | paced-1.0 | assign |
|---|---|---|---|---|---|---|---|---|
| 46 Days | N4 | N4 ✓ | N5 | N8 | N6 | N4 ✓ | N4 ✓ | N4 ✓ |
| Guyute | N4 | — | — | — | — | — | — | — |
| Maze | N4 | N6 | N8 | N5 | N4 ✓ | N6 | N6 | N7 |
| Esther | N4 | — | — | — | — | — | — | — |
| Gumbo | N4 | N8 | — | — | — | N9 | N9 | N4 ✓ |
| Brian and Robert | N4 | — | — | — | — | — | — | — |
| Stash | N4 | N4 ✓ | N7 | N5 | N6 | N5 | N5 | N8 |
| Moonage Daydream | N4 | N7 | N4 ✓ | N6 | — | — | — | N4 ✓ |
| The Curtain With | N4 | N9 | — | — | — | N9 | N9 | N7 |
| Fuego | N4 | N5 | N4 ✓ | N8 | N6 | N9 | N9 | N5 |
| Dark Puddle | N4 | — | — | — | — | — | — | — |
| Golden Age | N4 | N5 | N7 | N8 | N4 ✓ | N5 | N5 | N7 |
| Backwards Down the Number Line | N4 | N6 | N5 | N7 | N4 ✓ | N5 | N5 | N7 |
| Cavern | N4 | N6 | N5 | N8 | N4 ✓ | N6 | N6 | N6 |
| Possum | N4 | N6 | N5 | N8 | N4 ✓ | N6 | N6 | N5 |
| Fee | N4 | — | — | N9 | — | — | — | N5 |
| Tube | N4 | N4 ✓ | N5 | N8 | N7 | N4 ✓ | N4 ✓ | N6 |
| More | N4 | N6 | N5 | N7 | N4 ✓ | N4 ✓ | N4 ✓ | N4 ✓ |
| The Man Who Stepped Into Yesterday | N5 | — | — | — | — | — | — | — |
| The Lizards | N5 | N6 | N4 | N5 ✓ | N7 | N7 | N7 | N6 |
| Set Your Soul Free | N5 | N7 | — | N9 | N8 | N8 | N8 | N7 |
| Roggae | N5 | N5 ✓ | — | N4 | N9 | N7 | N7 | N6 |
| Ya Mar | N5 | N5 ✓ | — | — | N9 | N5 ✓ | N5 ✓ | N7 |
| The Dogs | N5 | N8 | N7 | — | — | N8 | N8 | N8 |
| Billy Breathes | N5 | N5 ✓ | — | — | — | N5 ✓ | N5 ✓ | — |
| It's Ice | N5 | N9 | — | — | N7 | N7 | N7 | — |
| Walls of the Cave | N5 | N7 | N4 | N5 ✓ | N6 | N6 | N6 | — |
| Pebbles and Marbles | N5 | N7 | N6 | N4 | N8 | N6 | N6 | N4 |
| What's Going Through Your Mind | N5 | N4 | N6 | N7 | N5 ✓ | N4 | N4 | N9 |
| Piper | N5 | N7 | N8 | N6 | N5 ✓ | N6 | N6 | — |
| Monsters | N5 | N4 | N6 | N7 | N5 ✓ | N4 | N4 | N5 ✓ |
| Life Saving Gun | N5 | N4 | N6 | N7 | N5 ✓ | N7 | N7 | N7 |
| What's the Use? | N5 | N5 ✓ | N8 | N4 | N6 | N8 | N8 | — |
| Vultures | N5 | — | — | — | — | — | — | — |
| Say It To Me S.A.N.T.O.S. | N5 | N5 ✓ | N6 | N7 | N4 | N4 | N4 | N9 |
| Slave to the Traffic Light | N5 | N6 | N4 | N7 | N5 ✓ | N9 | N9 | N9 |
| Timber (Jerry the Mule) | N6 | — | N9 | — | N7 | N7 | N7 | N6 ✓ |
| The Moma Dance | N6 | N4 | N7 | N5 | N8 | N4 | N4 | N4 |
| The Final Hurrah | N6 | N8 | N6 ✓ | — | — | N8 | N8 | N5 |
| Axilla (Part II) | N6 | N6 ✓ | N8 | N4 | N7 | N5 | N5 | N5 |
| Cities | N6 | — | N6 ✓ | N9 | N7 | N9 | N9 | N5 |
| Horn | N6 | — | — | — | N9 | — | — | — |
| The Well | N6 | N9 | N7 | N5 | N8 | N6 ✓ | N6 ✓ | N4 |
| My Soul | N6 | N5 | N7 | N4 | — | N5 | N5 | N6 ✓ |
| Halley's Comet | N6 | N6 ✓ | N5 | — | — | — | — | — |
| Blaze On | N6 | N6 ✓ | N5 | N4 | N7 | N5 | N5 | N6 ✓ |
| Chalk Dust Torture | N6 | N5 | N4 | N8 | N6 ✓ | N6 ✓ | N6 ✓ | N7 |
| Mercury | N6 | N4 | N6 ✓ | N8 | N5 | N4 | N4 | N4 |
| Waves | N6 | — | N8 | — | N7 | — | — | N8 |
| About to Run | N6 | N5 | N4 | N7 | N6 ✓ | N7 | N7 | — |
| Ghost | N6 | N5 | N6 ✓ | N7 | N4 | N4 | N4 | N7 |
| Bug | N6 | N8 | N5 | N6 ✓ | N4 | N5 | N5 | N5 |
| First Tube | N6 | N4 | N6 ✓ | N7 | N5 | N5 | N5 | N6 ✓ |
| The Wedge | N7 | — | N9 | N4 | N8 | — | — | N5 |
| NICU | N7 | N7 ✓ | — | — | — | N8 | N8 | — |
| Halfway to the Moon | N7 | — | — | — | — | — | — | — |
| Leaves | N7 | N6 | N5 | — | N8 | — | — | — |
| 555 | N7 | N6 | N7 ✓ | N4 | N8 | N7 ✓ | N7 ✓ | N5 |
| Dirt | N7 | — | — | — | — | N7 ✓ | N7 ✓ | — |
| Punch You in the Eye | N7 | N5 | N7 ✓ | N4 | N9 | N5 | N5 | N4 |
| Golgi Apparatus | N7 | N7 ✓ | N4 | N6 | N5 | N6 | N6 | N5 |
| A Song I Heard the Ocean Sing | N7 | N8 | — | — | N9 | N9 | N9 | N9 |
| A Wave of Hope | N7 | N5 | N6 | N7 ✓ | N4 | N5 | N5 | N4 |
| Prince Caspian | N7 | N5 | N7 ✓ | N6 | N4 | N6 | N6 | N8 |
| Lonely Trip | N7 | N5 | N7 ✓ | N6 | N4 | N5 | N5 | N4 |
| Runaway Jim | N7 | N7 ✓ | N9 | — | N8 | N7 ✓ | N7 ✓ | N9 |
| Sneakin' Sally Thru the Alley | N7 | — | N5 | N4 | N7 ✓ | N7 ✓ | N7 ✓ | N6 |
| Drift While You're Sleeping | N7 | N6 | N5 | N7 ✓ | N4 | N5 | N5 | N7 ✓ |
| The Sloth | N7 | — | — | — | — | — | — | — |
| The Squirming Coil | N7 | N6 | N4 | N9 | N5 | N6 | N6 | N9 |
| Sample in a Jar | N8 | N7 | — | — | N9 | N6 | N6 | N6 |
| Boogie On Reggae Woman | N8 | — | N4 | N5 | N7 | — | — | N4 |
| Heavy Things | N8 | — | — | — | — | — | — | N8 ✓ |
| Bouncing Around the Room | N8 | N6 | N8 ✓ | N4 | N7 | N5 | N5 | N6 |
| Mound | N8 | — | — | — | — | — | — | — |
| Mountains in the Mist | N8 | — | N8 ✓ | — | N7 | — | — | N8 ✓ |
| Stealing Time From the Faulty Plan | N8 | N8 ✓ | — | — | — | N8 ✓ | N8 ✓ | N8 ✓ |
| Tela | N8 | — | — | — | — | — | — | — |
| McGrupp and the Watchful Hosemasters | N8 | — | N7 | — | N8 ✓ | — | — | — |
| Wingsuit | N8 | N8 ✓ | — | — | N9 | N8 ✓ | N8 ✓ | — |
| David Bowie | N8 | N8 ✓ | N4 | N6 | N5 | N4 | N4 | N8 ✓ |
| Wilson | N8 | N7 | N4 | N5 | N6 | N7 | N7 | N6 |
| Seven Below | N8 | N7 | — | N5 | — | N6 | N6 | — |
| Plasma | N8 | N4 | N6 | N8 ✓ | N5 | N4 | N4 | N9 |
| Crosseyed and Painless | N8 | N8 ✓ | N9 | N4 | N6 | N5 | N5 | N4 |
| Pillow Jets | N8 | N4 | N7 | — | N5 | N4 | N4 | N4 |
| Shade | N8 | — | — | N8 ✓ | — | — | — | N8 ✓ |
| Sand | N8 | N4 | N6 | N7 | N5 | N8 ✓ | N8 ✓ | N8 ✓ |
| I Didn't Know | N8 | — | — | — | — | — | — | — |
| Saw It Again | N8 | — | — | — | N8 ✓ | — | — | — |
| Rock and Roll | N8 | N5 | N7 | N6 | N4 | N6 | N6 | N7 |
| Farmhouse | N9 | N7 | N6 | N5 | N8 | N8 | N8 | N8 |
| Undermind | N9 | N8 | — | — | — | N8 | N8 | N5 |
| Ocelot | N9 | N6 | — | — | — | N6 | N6 | — |
| Back on the Train | N9 | N4 | N5 | N9 ✓ | N6 | N4 | N4 | N5 |
| Ether Edge | N9 | N7 | N4 | N6 | N5 | N6 | N6 | — |
| Llama | N9 | N9 ✓ | N8 | — | — | N7 | N7 | N6 |
| The Horse | N9 | — | N7 | N6 | — | N8 | N8 | N9 ✓ |
| Silent in the Morning | N9 | — | N9 ✓ | N6 | — | N8 | N8 | — |
| Taste | N9 | N4 | N5 | N8 | N6 | N4 | N4 | N5 |
| Julius | N9 | N8 | N4 | N5 | N6 | N7 | N7 | N6 |
| Frankenstein | N9 | — | — | — | — | — | — | — |
| Kill Devil Falls | N9 | N4 | N5 | N8 | N6 | N4 | N4 | N6 |
| Ruby Waves | N9 | N4 | N6 | N7 | N5 | N4 | N4 | N6 |
| Meatstick | N9 | N5 | N6 | N8 | N4 | N8 | N8 | N6 |
| My Friend, My Friend | N9 | N5 | N4 | N7 | N6 | N5 | N5 | N7 |
| A Life Beyond The Dream | N9 | N4 | N6 | N7 | N5 | N5 | N5 | N9 ✓ |
| Character Zero | N9 | N4 | N6 | N7 | N5 | N4 | N4 | N8 |
| Wading in the Velvet Sea | N9 | N8 | N4 | N5 | N6 | N9 ✓ | N9 ✓ | N8 |
| Fluffhead | N9 | N6 | N5 | N8 | N4 | N7 | N7 | N5 |

### Surprises (songs no variant predicted)

- Guyute _(N4)_
- Esther _(N4)_
- Brian and Robert _(N4)_
- Dark Puddle _(N4)_
- The Man Who Stepped Into Yesterday _(N5)_
- Vultures _(N5)_
- Halfway to the Moon _(N7)_
- The Sloth _(N7)_
- Mound _(N8)_
- Tela _(N8)_
- I Didn't Know _(N8)_
- Frankenstein _(N9)_

## Actual setlists (for reference)

### 2026-04-23

**Set 1**
- 1. 46 Days
- 2. Guyute
- 3. Maze
- 4. Esther
- 5. Gumbo
- 6. Brian and Robert
- 7. Stash
- 8. Moonage Daydream
**Set 2**
- 9. The Curtain With
- 10. Fuego
- 11. Dark Puddle
- 12. Golden Age
- 13. Fuego
- 14. Backwards Down the Number Line
- 15. Cavern
- 16. Possum
**Encore**
- 17. Fee
- 18. Tube
- 19. More

### 2026-04-24

**Set 1**
- 1. The Man Who Stepped Into Yesterday
- 2. The Lizards
- 3. Set Your Soul Free
- 4. Roggae
- 5. Ya Mar
- 6. The Dogs
- 7. Billy Breathes
- 8. It's Ice
- 9. Walls of the Cave
**Set 2**
- 10. Pebbles and Marbles
- 11. What's Going Through Your Mind
- 12. Piper
- 13. Monsters
- 14. Life Saving Gun
- 15. What's the Use?
- 16. Vultures
- 17. Say It To Me S.A.N.T.O.S.
**Encore**
- 18. Slave to the Traffic Light

### 2026-04-25

**Set 1**
- 1. Timber (Jerry the Mule)
- 2. The Moma Dance
- 3. The Final Hurrah
- 4. Axilla (Part II)
- 5. Cities
- 6. Horn
- 7. The Well
- 8. My Soul
**Set 2**
- 9. Halley's Comet
- 10. Blaze On
- 11. Chalk Dust Torture
- 12. Mercury
- 13. Waves
- 14. About to Run
- 15. Ghost
**Encore**
- 16. Bug
- 17. First Tube

### 2026-04-30

**Set 1**
- 1. The Wedge
- 2. NICU
- 3. Halfway to the Moon
- 4. Leaves
- 5. 555
- 6. Dirt
- 7. Punch You in the Eye
- 8. Golgi Apparatus
**Set 2**
- 9. A Song I Heard the Ocean Sing
- 10. A Wave of Hope
- 11. Prince Caspian
- 12. Lonely Trip
- 13. Runaway Jim
- 14. Sneakin' Sally Thru the Alley
- 15. Drift While You're Sleeping
**Encore**
- 16. The Sloth
- 17. The Squirming Coil

### 2026-05-01

**Set 1**
- 1. Sample in a Jar
- 2. Boogie On Reggae Woman
- 3. Heavy Things
- 4. Bouncing Around the Room
- 5. Mound
- 6. Mountains in the Mist
- 7. Stealing Time From the Faulty Plan
- 8. Tela
- 9. McGrupp and the Watchful Hosemasters
- 10. Wingsuit
- 11. David Bowie
**Set 2**
- 12. Wilson
- 13. Seven Below
- 14. Plasma
- 15. Crosseyed and Painless
- 16. Pillow Jets
- 17. Shade
- 18. Sand
**Encore**
- 19. I Didn't Know
- 20. Saw It Again
- 21. Rock and Roll

### 2026-05-02

**Set 1**
- 1. Farmhouse
- 2. Undermind
- 3. Ocelot
- 4. Back on the Train
- 5. Ether Edge
- 6. Llama
- 7. The Horse
- 8. Silent in the Morning
- 9. Taste
- 10. Julius
**Set 2**
- 11. Frankenstein
- 12. Kill Devil Falls
- 13. Ruby Waves
- 14. Meatstick
- 15. My Friend, My Friend
- 16. A Life Beyond The Dream
- 17. Character Zero
**Encore**
- 18. Wading in the Velvet Sea
- 19. Fluffhead

