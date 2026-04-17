# Phishpicker — Design

**Date:** 2026-04-16
**Status:** Design approved, ready for implementation planning
**Purpose:** Analyze all Phish setlist history to predict the next song during a live show.

## Goal

A data-analysis app that ranks the most likely next song Phish will play, updated in real time as songs are entered during a show. Offline analysis + manual live-predict UI. Public-facing web UI on the NAS behind Cloudflare/Authentik. For fun, not profit.

## Core insight

Phish's setlist logic is dominated by *constraints and context* (don't repeat in a run, song-pairing affinities, venue-residency patterns, era-specific rotation), not deep audio-sequence dependencies. That means hand-engineered features over historical setlist data should carry most of the signal, and a gradient-boosted ranker will be the sweet spot: strong accuracy, interpretable outputs, fast to train.

## Decisions summary

| Decision | Choice | Why |
|---|---|---|
| Data source | phish.net API v5, fresh pull on first run, full backfill (~1,900 shows) | Only authoritative source; user already has API key |
| MVP scope | Offline analysis + manual live-predict UI (no automated in-show ingestion) | 95% of value at 40% of work; live-feed plumbing is deferred |
| UI output | Leaderboard + reasoning + song lookup, built in stages | Leaderboard first; reasoning and lookup layer on once model is sound |
| Prediction target | Next song given context so far tonight | Hardest, highest-signal target; others derive from it |
| Stack | Python (FastAPI + LightGBM) backend + Next.js frontend | Best tool for each; data work in Python, UI in TS |
| Deployment | Docker compose on NAS; Cloudflare tunnel; Authentik auth; training on Mac mini | Reuse existing infra; Mac mini is fastest available for training |
| Model | LightGBM LambdaRank with ~30 hand-engineered features | Small data + combinatorial signal + interpretability need = trees |
| Evaluation | Walk-forward validation over last 20 shows; production trains on all data | Matches reality; no awkward "re-include holdout" question |
| Auth | Authentik in front of web container only; API on internal network | Single auth integration; API unreachable from internet |

## Architecture

```
┌─────────────────┐      ┌─────────────────────────────────┐
│  Mac mini       │      │  NAS (Docker host)              │
│  (training)     │      │                                 │
│                 │      │  ┌─────────────┐  ┌───────────┐ │
│  • hourly poll  │ ───▶ │  │ api         │  │ web       │ │
│    of phish.net │ scp  │  │ FastAPI +   │  │ Next.js   │ │
│  • ingest on    │      │  │ LightGBM    │  │ (static)  │ │
│    new shows    │      │  │ model.pkl   │  │           │ │
│  • retrain +    │      │  └──────▲──────┘  └─────▲─────┘ │
│    ship         │      │         │               │       │
└─────────────────┘      │         └── SQLite ─────┘       │
                         │              volume             │
                         └─────────────────────────────────┘
                                          ▲
                                 Cloudflare Tunnel + Authentik
                                          ▼
                                  phishpicker.<domain>
```

- **Mac mini** runs the training pipeline. Poll hourly; retrain only when new shows land. Atomic-rename deploy to NAS via `ssh nas-ssh`.
- **NAS `api` container**: Python 3.12 + FastAPI. Loads model at startup. Stateless read side. Writes `live.db` for in-progress show state.
- **NAS `web` container**: Next.js App Router. Proxies API over the internal Docker network. Only this container is exposed publicly.
- **Single `docker-compose.yml`** brings both up together.

## Data model

### `phishpicker.db` — historical truth, built on Mac mini, shipped read-only

```sql
songs          (song_id PK, name, original_artist, debut_date, first_seen_at)
venues         (venue_id PK, name, city, state, country)
tours          (tour_id PK, name, start_date, end_date)
shows          (show_id PK, show_date, venue_id FK, tour_id FK,
                run_position, run_length, tour_position,
                fetched_at, reconciled)
setlist_songs  (show_id FK, set_number, position, song_id FK, trans_mark,
                PRIMARY KEY (show_id, set_number, position))
features       (show_id FK, song_id FK, context_hash, feature_json, computed_at)
model_meta     (trained_at, data_through_show_id, model_version, metrics_json)
```

### `live.db` — NAS-local, written by API

```sql
live_show  (show_id PK, show_date, venue_id, started_at, reconciled_at)
live_songs (show_id FK, entered_order, song_id FK, set_number, trans_mark,
            entered_at, PRIMARY KEY (show_id, entered_order))
```

## Ingestion pipeline

1. Hourly poll of `/shows.json?order_by=showdate&direction=desc&limit=5`. Exit if nothing new.
2. Fetch `/setlists/get.json` per new show; upsert into `shows` + `setlist_songs`.
3. Refresh song/venue catalogs opportunistically.
4. Derive `run_position`, `run_length`, `tour_position` for new shows.
5. Regenerate `features` table (incremental — only what depends on new data).
6. Train + evaluate (see below).
7. Atomic-ship: `scp *.new` + rename + `POST /internal/reload`.
8. Reconcile any live-show rows whose date is now covered by phish.net.

## Features (~30 across seven families)

1. **Song base rates** — total plays, recent plays, historical gap mean, debut year, is_cover.
2. **Recency** — shows/days since last played, last_played_this_tour, last_played_this_run.
3. **Venue & run** — times at venue, shows since last at venue, played_already_this_run, run_position, venue_debut_affinity.
4. **Tour** — tour_position, times_this_tour, tour_opener_rate, tour_closer_rate.
5. **In-show context** — current_set, set_position, set-role rates, previous_song_id, transition bigram/trigram scores, in-set co-occurrence, segue_mark_in.
6. **Temporal / era** — day_of_week, month, days_since_last_new_album, is_from_latest_album, era (1.0/2.0/3.0/4.0).
7. **Song roles (derived)** — opener_score, closer_score, encore_score, middle_of_set_2_score (jam-vehicle proxy), bustout_score.

No manual tagging. All role features derived from setlist position history.

### Hard rules applied post-scoring

- Song already played tonight → probability = 0.
- Song played earlier this run → probability × 0.01.
- No prior song entered → use opener-weighted variant.

### Cold-start handling

New songs use original-artist and debut-year priors. First-show-of-tour uses `tour_position=1` naturally. Pre-show leaderboard uses context-free features + `set_1_opener_rate`.

## Modeling

- **Algorithm**: LightGBM LambdaRank.
- **Training groups**: `(show_id, slot_number)`; ~42,000 groups × ~950 candidates.
- **Hard-negative sampling**: 50 per positive, biased to high-frequency songs. [Flagged for revisit if metrics underperform.]
- **Recency weighting**: `sample_weight` with 7-year exponential half-life. [Flagged for empirical tuning.]
- **Era feature** included alongside recency weighting; compare both-on vs only-era on test set, ship simpler if within noise.

### Secondary jam-length model

LightGBM regressor on `(song, set_position, venue, era, previous_song)` → predicted seconds, trained on phish.in track durations. Shipped as `jam_length_model.pkl`. [Deferrable to v1.1 if phish.in scraping is messy.]

### Evaluation

- **Production model**: trained on *all* available data.
- **Reported metrics**: walk-forward over last 20 shows — for each, fit on prior-only data, predict, aggregate.
- **Sanity-check**: fixed holdout (≤2023 train, 2024–25 test) run once per major model change.

### Metrics (reported every ship)

| Metric | Target |
|---|---|
| Top-1 | > 8% |
| Top-5 | > 25% |
| Top-20 | > 55% |
| MRR | > 0.15 |

Baselines shown next to every eval: random, frequency-only, heuristic rules (Approach 1), current LightGBM. If LightGBM doesn't beat the heuristic, ship the heuristic.

### Ship gate

Retrain must not drop MRR by more than 0.02 from the previous model without explicit override. Prevents silently shipping a regression.

## API surface

```
GET    /meta
GET    /songs
GET    /venues
GET    /shows?limit=&offset=
POST   /live/show
DELETE /live/show/{show_id}
POST   /live/song
DELETE /live/song/last
POST   /live/set-boundary
GET    /predict/{show_id}
GET    /predict/{show_id}/bustouts
GET    /songs/{song_id}/stats
POST   /internal/reload         (loopback only)
```

**Perf target**: `/predict` p50 < 100ms for ~950 candidates.

## UI (Next.js App Router)

1. **`/` — Home / Live Prediction.** Leaderboard (top-20), Bust-out Watch sidebar, played-tonight strip with undo, sticky "+" song-add sheet with client-side fuzzy type-ahead over ~950 songs. Mobile-first, one-handed, dark.
2. **`/shows` — Archive browser.** Paginated; replay-mode per show.
3. **`/shows/[id]` — Show detail & replay.** What we'd have predicted slot-by-slot vs. truth.
4. **`/songs/[id]` — Song detail.** Gap, plays, venue history, role scores, expected jam length, external links.
5. **`/about` — Meta.** Metrics, training history, deferred decisions, "how this works."

**Every page footer**: "Model updated {ago} · {shows} shows · {songs} songs · v{version}".

**Set boundaries**: explicit button tap. No inference.

## Live-show UX (the one-handed test)

```
Pre-show:   "Start show" → auto-fill date + venue → confirm → openers
            leaderboard appears.
Per song:   Tap "+" → type 3–4 letters → pick → pick segue mark → done.
            Leaderboard re-ranks in ~200ms.
Setbreak:   One-tap boundary button → leaderboard pivots to Set 2 context.
Oops:       Tap last played song → undo → restored.
End:        "End show" → replay scorecard view.
Next day:   Auto-reconciled against phish.net's published setlist.
```

~3 taps per song; back to watching the band before the next one starts.

## Testing

| Layer | What | When |
|---|---|---|
| Unit | feature calcs, scoring math, hard rules | every commit |
| Integration | ingestion (fixtures), training on mini DB, API endpoints | every commit |
| Model regression | metrics thresholds | on ship |
| UI components | type-ahead, leaderboard, add/undo | every commit |
| E2E smoke | start-show → add-songs → predictions update | on ship + manual |

**Must-have tests before v1 ships:**

- Hard rules filter played-tonight songs.
- Feature determinism (training-serving skew guard).
- Atomic deploy doesn't corrupt API.
- Ingestion idempotency.
- Feature/model schema alignment on API startup.
- Walk-forward metric threshold gate.

## Deferred decisions (flagged for revisit)

- **Hard-negative sampling (50/positive)** — revert to full candidate set if metrics underperform.
- **Recency half-life (7 years)** — empirically tune if era-drift shows in metrics.
- **Jam-length model** — v1 or v1.1 depending on phish.in data access.
- **Model calibration** (isotonic regression) — add when UI starts showing probabilities as numbers.
- **Era-sensitivity report** — a per-feature "what's changed" view for Phish nerdery.

## Future phases (not in v1)

- **v1.1** — Current-song stats side panel; share-scorecard image export; PWA manifest.
- **v2** — Automated in-show ingestion (poll phish.net / phish.in), websocket push to UI for realtime updates, multi-device sync.

## What I considered and cut (YAGNI)

- Weather / attendance / fatigue features — too noisy, too much plumbing.
- Audio features (lyrics, tempo, key) — Phish's logic is context, not audio.
- Neural sequence model (transformer) — overkill for the data size; interpretability would suffer.
- Per-era separate models — one model + era feature is simpler.
- Online learning — retrain is cheap enough.
- Postgres — SQLite is plenty.
- Manual song tagging (jam vehicle Y/N) — derived features capture it without maintenance burden.
- Prometheus / heavy observability — `/meta` + structured logs suffice.
- Load testing — audience of one.

## Setup prerequisites

- Generate SSH key on Mac mini; add pubkey to `~/.ssh/authorized_keys` on NAS (one-time).
- Store phish.net API key on Mac mini (env file, not committed).
- Reserve a subdomain + Cloudflare tunnel route + Authentik app.
- Provision `/volume/phishpicker/data` on NAS for the SQLite + model artifacts.
