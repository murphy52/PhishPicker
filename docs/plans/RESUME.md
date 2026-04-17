# Resume Point — 2026-04-16

Session paused mid-execution. Pick up here next time.

## Current state

- **Branch:** `main`
- **HEAD:** `86a8682` — `feat: /predict endpoint with heuristic scoring and hard-rule filter`
- **Test suite:** `cd api && uv run pytest -v` → 57 passing
- **Ruff:** `cd api && uv run ruff check .` → clean
- **Working tree:** clean

## Progress (16 of 21 implementation tasks complete)

| Plan task | Commit(s) | Status |
|---|---|---|
| Task 0 — Repo hygiene | `00295d6` | ✅ |
| Task 1 — Python backend scaffold | `e79172a` | ✅ |
| Task 2 — Next.js frontend scaffold | `176ce52` | ✅ |
| Task 3 — SQLite schema | `e25812e` + fixes | ✅ |
| Task 4 — Live-show schema | `f57cda9` | ✅ |
| Extra — CHECK constraints | `ac92896` | ✅ |
| Task 5 — phish.net API client | `46733c9` + `b0945b1` | ✅ |
| Task 6 — Ingestion songs/venues | `9be3bdd` | ✅ |
| Task 7 — Ingestion shows/setlists + derived fields | `261279d` | ✅ |
| Task 8 — Orchestrator + CLI | `8525f30` | ✅ |
| Task 9 — Heuristic scorer | `6cb83a3` | ✅ |
| Task 10 — Stats extractor | `e502c81` | ✅ |
| Task 11 — Hard-rule post-processor | `f5e195f` | ✅ |
| Task 12 — FastAPI app + /meta | `acc91bf` | ✅ |
| Task 13 — /songs + live-show endpoints | `7c9ee8b` | ✅ |
| Task 14 — /predict endpoint | `86a8682` | ✅ |
| Tasks 15–20 | — | ⏳ pending |

## Next actions on resume

1. Verify clean state:
   ```bash
   cd /Users/David/phishpicker
   git log --oneline | head -3   # HEAD = 86a8682
   git status                    # clean
   cd api && uv run pytest -v    # 57 passing
   ```

2. Continue with Task 15 — Web proxy + song search (Next.js).

3. **Read the plan carefully before dispatching Task 15 and 16** — they have deferred TODOs from the Task 2 frontend review embedded in their descriptions.

4. Continue subagent-driven pattern.

## Remaining tasks (from the plan)

- Task 15 — Web proxy + song search (`web/src/app/api/[...path]/route.ts` + `web/src/lib/songs.ts`)
- Task 16 — Web live-show UI (`web/src/app/page.tsx` + components)
- Task 17 — Dockerfiles + compose
- Task 18 — Mac mini ship script
- Task 19 — Deployment docs
- Task 20 — E2E smoke validation

## Key reference files

- `docs/plans/2026-04-16-phishpicker-design.md` — full design
- `docs/plans/2026-04-16-walking-skeleton.md` — implementation plan

## Known caveats for upcoming tasks

- **Next.js 16** (plan assumed 15): async `params` pattern applies in Task 15 route handlers.
- **Tasks 15 & 16** have deferred fixes from the Task 2 frontend scaffold review — read plan carefully before dispatching.
- **Tour stubs**: pipeline inserts `[stub] tour N` rows. Future real tour loader must use `ON CONFLICT DO UPDATE`.
- **No pagination guard** on phish.net shows — add count sanity check before first real ingest.
- **API key**: `.env` has 19-char `PHISHNET_API_KEY` — verify completeness before first real ingest.
