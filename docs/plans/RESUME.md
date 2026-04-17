# Resume Point — 2026-04-16

Session paused mid-execution. Pick up here next time.

## Current state

- **Branch:** `main`
- **HEAD:** `8525f30` — `feat: ingestion pipeline orchestrator and cli`
- **Test suite:** `cd api && uv run pytest -v` → 25 passing
- **Ruff:** `cd api && uv run ruff check .` → clean
- **Working tree:** clean

## Progress (10 of 21 implementation tasks complete)

| Plan task | Commit(s) | Status |
|---|---|---|
| Task 0 — Repo hygiene | `00295d6` | ✅ |
| Task 1 — Python backend scaffold | `e79172a` | ✅ |
| Task 2 — Next.js frontend scaffold | `176ce52` | ✅ |
| Task 3 — SQLite schema | `e25812e` + `e63aad9` + `1e01d4f` | ✅ |
| Task 4 — Live-show schema | `f57cda9` | ✅ |
| Extra — CHECK constraints | `ac92896` | ✅ |
| Task 5 — phish.net API client | `46733c9` + `b0945b1` (fixes) | ✅ |
| Task 6 — Ingestion songs/venues upsert | `9be3bdd` | ✅ |
| Task 7 — Ingestion shows/setlists + derived fields | `261279d` | ✅ |
| Task 8 — Orchestrator + CLI | `8525f30` | ✅ |
| Tasks 9–20 | — | ⏳ pending |

## Next actions on resume

1. Verify clean state:
   ```bash
   cd /Users/David/phishpicker
   git log --oneline | head -3   # HEAD = 8525f30
   git status                    # clean
   cd api && uv run pytest -v    # 25 passing
   ```

2. Continue with Task 9 — Heuristic scorer.

3. Continue subagent-driven pattern — fresh implementer per task, spec review, quality review, commit.

## Remaining tasks (from the plan)

- Task 9 — Heuristic scorer
- Task 10 — Stats extractor
- Task 11 — Hard-rule post-processor
- Task 12 — FastAPI app + /meta
- Task 13 — /songs + live-show endpoints
- Task 14 — /predict endpoint
- Task 15 — Web proxy + song search (has deferred TODOs — see plan)
- Task 16 — Web live-show UI (has deferred TODOs — see plan)
- Task 17 — Dockerfiles + compose
- Task 18 — Mac mini ship script
- Task 19 — Deployment docs
- Task 20 — E2E smoke validation

## Key reference files

- `docs/plans/2026-04-16-phishpicker-design.md` — full design
- `docs/plans/2026-04-16-walking-skeleton.md` — implementation plan

## Known caveats for upcoming tasks

- **No pagination guard** on phish.net shows: pipeline may silently truncate. Add count sanity check (`if len(shows) < 1500: log warning`) before first real ingest.
- **API key**: `.env` has a 19-char `PHISHNET_API_KEY` — verify it's complete before first real ingest.
- **Tour stubs**: pipeline inserts `[stub] tour N` rows via `INSERT OR IGNORE`. Future real tour loader must use `ON CONFLICT DO UPDATE` to replace stubs.
- **`showid` field name**: verify against live API before first production ingest.
- **Tasks 15 & 16** have deferred fixes from Task 2 review — read plan carefully before dispatching.
- **Next.js 16** (plan assumed 15): async `params` pattern still applies in Task 15.
