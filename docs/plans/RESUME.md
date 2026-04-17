# Resume Point — 2026-04-17

Walking skeleton complete. All 20 tasks committed and tagged v0.1.0-skeleton.

## Current state

- **Branch:** `main`
- **Tag:** `v0.1.0-skeleton`
- **API tests:** `cd api && uv run pytest -q` → 60 passing
- **Web tests:** `cd web && npm test` → 48 passing
- **Web build:** `cd web && npm run build` → clean (standalone output)
- **Working tree:** clean

## Tasks complete (all 20)

| Task | Description | Status |
|---|---|---|
| Task 0 | Repo hygiene | ✅ |
| Task 1 | Python backend scaffold | ✅ |
| Task 2 | Next.js frontend scaffold | ✅ |
| Task 3 | SQLite schema | ✅ |
| Task 4 | Live-show schema | ✅ |
| Task 5 | phish.net API client | ✅ |
| Task 6 | Ingestion songs/venues | ✅ |
| Task 7 | Ingestion shows/setlists + derived fields | ✅ |
| Task 8 | Orchestrator + CLI | ✅ |
| Task 9 | Heuristic scorer | ✅ |
| Task 10 | Stats extractor | ✅ |
| Task 11 | Hard-rule post-processor | ✅ |
| Task 12 | FastAPI app + /meta | ✅ |
| Task 13 | /songs + live-show endpoints | ✅ |
| Task 14 | /predict endpoint | ✅ |
| Task 15 | Web proxy + song search + songs lib | ✅ |
| Task 16 | Live-show UI (leaderboard, played strip, add-song sheet) | ✅ |
| Task 17 | Dockerfiles + docker-compose stack | ✅ |
| Task 18 | Mac mini ingest-and-ship script + /internal/reload | ✅ |
| Task 19 | Deployment docs | ✅ |
| Task 20 | E2E smoke validation (local verified; NAS+Cloudflare pending manual) | ✅ |

## Pending manual verification (requires NAS + Cloudflare access)

- `docker compose up -d` on NAS → visit through Cloudflare tunnel
- `/meta` shows non-zero shows_count after first ingest
- Phone browser: start show, add songs, leaderboard re-ranks
- Undo, set boundary, refresh persistence
- Predict latency <500ms on NAS

## Next plans

See end of `docs/plans/2026-04-16-walking-skeleton.md` for carry-forward notes.
The next plan should cover the LightGBM model (feature engineering, training
pipeline, walk-forward eval, ship gate, /about metrics display).
