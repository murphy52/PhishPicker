# Live Picker Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the existing `web/` Next.js app and `api/` FastAPI backend with
a live-during-a-Phish-show UI: auto-load tonight's show, display a grayed-out
predicted setlist (9/7/2 default), show per-slot top-10 alternatives, typeahead
song entry, undo stack, set transitions, bustout handling, and background
phish.net reconciliation.

**Architecture:** Builds on existing FastAPI `/live/*` endpoints and existing
React components. Source of truth for session state is SQLite
(`live_show`/`live_songs` + a new tiny `live_show_meta` table). Preview is
stateless — a loop over a new pure `POST /predict` endpoint. Phish.net sync
runs as an app-state-scoped `PollerRegistry`; each tick opens its own DB
connection.

**Tech Stack:** Python 3.12 / FastAPI / sqlite3 / httpx · Next.js 16 / React
19 / TypeScript / Tailwind 4 / SWR / fuse.js / Vitest.

**Design doc:** `docs/plans/2026-04-21-live-picker-design.md` (see the
"Revision note (post-team-review)" section at the top of the Frontend layout
section — that supersedes earlier design ambiguities).

**Testing commands:**
- Backend single test: `cd api && uv run pytest tests/<file>::<test> -v`
- Backend suite: `cd api && uv run pytest -q`
- Backend lint: `cd api && uv run ruff check src tests`
- Frontend tests: `cd web && npm test`
- Frontend lint: `cd web && npm run lint`

**⚠ Next.js 16 caveat:** `web/AGENTS.md` warns APIs may differ from training
data. Before writing Next server code, read
`web/node_modules/next/dist/docs/`. Existing code in this repo (especially
`web/src/app/page.tsx` and `web/src/app/api/[...path]/route.ts`) is the
authoritative reference. House test style is `screen.getByText(...)`, NOT
`const { getByText } = render(...)`.

---

## Existing code reference (verified against repo)

Backend:
- `api/src/phishpicker/app.py` — `/meta`, `/about`, `/songs`,
  `/predict/{show_id}`, `/live/show`, `/live/show/{id}`, `/live/song`,
  `DELETE /live/song/last`, `/live/set-boundary`, `/internal/reload`.
  Lifespan sets `app.state.scorer`. Dep factories: `get_read`, `get_live`.
- `api/src/phishpicker/live.py` — `create_live_show`, `append_song`,
  `delete_last_song`, `advance_set`, `get_live_show`.
- `api/src/phishpicker/predict.py` — `predict_next(read, live, show_id, top_n, scorer)`.
- `api/src/phishpicker/phishnet/client.py` — `PhishNetClient` with public
  `fetch_all_shows`, `fetch_setlist(show_id)`, `fetch_songs`, `fetch_venues`.
  **No** `fetch_upcoming_shows`, **no** `fetch_setlist_by_date` — both must
  be added. `._get` is private; do not call it from outside the class.
- `api/src/phishpicker/config.py` — `Settings` has `phishnet_api_key`;
  `db_path`, `live_db_path` are `@property` methods (use `settings.db_path`).
- `api/src/phishpicker/db/connection.py` — `open_db(path, read_only)`,
  `apply_schema(conn)`. Schema lives at `db/schema.sql`. No migration system.
- `api/tests/conftest.py` — has `seeded_client` fixture (NOT `api_client`);
  we'll add a bare fixture as needed.

Frontend:
- `web/src/app/page.tsx` — main picker; uses SWR, `useLiveShow` hook.
- `web/src/app/api/[...path]/route.ts` — transparent proxy to FastAPI; any
  FastAPI endpoint is reachable at `/api/<same-path>`.
- `web/src/lib/liveShow.ts` — `useLiveShow()` hook.
- `web/src/components/` — `Leaderboard`, `SongSearch`, `AddSongSheet`,
  `PlayedStrip`, `SetBoundaryButton` (all with `.test.tsx`).
- `web/vitest.config.ts` — has `globals: true` + jest-dom setup; no imports
  needed for `test`, `expect`.

---

## Phase 1 — Foundations

### Task 0: Baseline verify

**Step 1:** Run backend suite.
```bash
cd /Users/David/phishpicker/api && uv run pytest -q
```
Expected: all tests pass (225 after retro harness).

**Step 2:** Run backend lint.
```bash
cd /Users/David/phishpicker/api && uv run ruff check src tests
```
Expected: clean.

**Step 3:** Run frontend tests.
```bash
cd /Users/David/phishpicker/web && npm test
```
Expected: pass (or "No test files" — both are fine).

**Step 4:** Boot API locally (if feasible — skip if env not set up).
```bash
cd /Users/David/phishpicker/api && uv run uvicorn phishpicker.app:create_app --factory --port 8000 &
curl http://localhost:8000/meta
kill %1
```
If `PHISHPICKER_DATA_DIR` etc. aren't set, skip — just note in a comment
that deployment testing needs the env.

**Step 5:** No commit — this is a read-only gate.

---

### Task 1: Schema additions — `is_bustout_placeholder`, `source`, `superseded_by`, `live_show_meta`

**Files:**
- Modify: `api/src/phishpicker/db/schema.sql`
- Modify: `api/src/phishpicker/db/connection.py` (idempotent one-time migrations)
- Create: `api/tests/test_schema_additions.py`

**Step 1: Failing test**

```python
# api/tests/test_schema_additions.py
import sqlite3
from phishpicker.db.connection import apply_schema


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_songs_has_is_bustout_placeholder():
    conn = sqlite3.connect(":memory:")
    apply_schema(conn)
    assert "is_bustout_placeholder" in _cols(conn, "songs")


def test_live_songs_has_source_and_superseded_by():
    # note: live_schema.sql, not schema.sql
    from phishpicker.db.connection import apply_live_schema
    conn = sqlite3.connect(":memory:")
    apply_live_schema(conn)
    cols = _cols(conn, "live_songs")
    assert "source" in cols
    assert "superseded_by" in cols


def test_live_show_meta_table_exists():
    from phishpicker.db.connection import apply_live_schema
    conn = sqlite3.connect(":memory:")
    apply_live_schema(conn)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    assert "live_show_meta" in tables
    cols = _cols(conn, "live_show_meta")
    for c in ["show_id", "sync_enabled", "last_updated", "last_error",
              "set1_size", "set2_size", "encore_size"]:
        assert c in cols
```

**Step 2:** Run — confirm failure.

**Step 3: Edit `db/schema.sql`**

In the songs CREATE TABLE (line 8), add the new column:
```sql
CREATE TABLE IF NOT EXISTS songs (
    song_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    original_artist TEXT,
    debut_date TEXT,
    first_seen_at TEXT NOT NULL,
    is_bustout_placeholder INTEGER NOT NULL DEFAULT 0
);
```

**Step 4: Edit `db/live_schema.sql`** (find it via `ls api/src/phishpicker/db/`)

- Add to `live_songs` CREATE TABLE:
  ```sql
  source TEXT NOT NULL DEFAULT 'user',
  superseded_by INTEGER
  ```
- Add new table:
  ```sql
  CREATE TABLE IF NOT EXISTS live_show_meta (
      show_id TEXT PRIMARY KEY REFERENCES live_show(show_id) ON DELETE CASCADE,
      sync_enabled INTEGER NOT NULL DEFAULT 0,
      last_updated TEXT,
      last_error TEXT,
      set1_size INTEGER NOT NULL DEFAULT 9,
      set2_size INTEGER NOT NULL DEFAULT 7,
      encore_size INTEGER NOT NULL DEFAULT 2
  );
  ```

**Step 5: Idempotent migration in `connection.py`**

In `apply_schema`, after the `executescript`:
```python
# One-time additive migration for pre-existing DBs.
for alter in [
    "ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER NOT NULL DEFAULT 0",
]:
    try:
        conn.execute(alter); conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
```

In `apply_live_schema`, same pattern for the two new `live_songs` columns
(`live_show_meta` CREATE TABLE is IF NOT EXISTS so it's already idempotent).

**Step 6:** Run — pass.

**Step 7: Commit**
```bash
git commit -am "feat(schema): bustout flag on songs; source/superseded_by on live_songs; live_show_meta table"
```

---

### Task 2: `PhishNetClient.fetch_upcoming_shows` + `fetch_setlist_by_date`

**Files:**
- Modify: `api/src/phishpicker/phishnet/client.py`
- Create: `api/tests/test_phishnet_client_additions.py`

**Step 1: Failing test**

```python
import pytest
from pytest_httpx import HTTPXMock
from phishpicker.phishnet.client import PhishNetClient


def test_fetch_upcoming_shows_filters_by_date_and_phish(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=k&order_by=showdate&direction=asc",
        json={"data": [
            {"showid": 1, "showdate": "2026-01-01", "artist_name": "Phish", "venue": "V", "city": "C", "state": "S"},
            {"showid": 2, "showdate": "2026-04-23", "artist_name": "Phish", "venue": "Sphere", "city": "Las Vegas", "state": "NV"},
            {"showid": 3, "showdate": "2026-04-24", "artist_name": "TAB", "venue": "x", "city": "x", "state": "x"},
        ]},
    )
    with PhishNetClient(api_key="k") as c:
        shows = c.fetch_upcoming_shows(from_date="2026-04-20")
    assert [s["showid"] for s in shows] == [2]


def test_fetch_setlist_by_date_filters_to_phish(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={"data": [
            {"songid": 1, "song": "Buried Alive", "set": "1", "position": 1, "artist_name": "Phish"},
            {"songid": 99, "song": "Other", "set": "1", "position": 1, "artist_name": "TAB"},
        ]},
    )
    with PhishNetClient(api_key="k") as c:
        rows = c.fetch_setlist_by_date("2026-04-23")
    assert len(rows) == 1
    assert rows[0]["song"] == "Buried Alive"
```

**Step 2:** Run — failure.

**Step 3: Implement**

```python
def fetch_upcoming_shows(self, from_date: str) -> list[dict]:
    """Phish-only shows on or after from_date (YYYY-MM-DD), asc by date."""
    data = self._get("shows.json", {"order_by": "showdate", "direction": "asc"})
    return [
        d for d in data
        if str(d.get("artist_name")) == "Phish"
        and str(d.get("showdate", "")) >= from_date
    ]


def fetch_setlist_by_date(self, show_date: str) -> list[dict]:
    """Phish-only rows for the show on show_date."""
    data = self._get(f"setlists/showdate/{show_date}.json", {})
    return [d for d in data if str(d.get("artist_name")) == "Phish"]
```

**Step 4:** Run — pass.

**Step 5: Commit**
```bash
git commit -am "feat(phishnet): fetch_upcoming_shows + fetch_setlist_by_date public methods"
```

---

### Task 3: `/upcoming` endpoint (with timezone + start_time)

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Create: `api/tests/test_upcoming.py`

**Design:** Returns `{show_id, show_date, venue, city, state, timezone, start_time_local}`.
For now, derive `timezone` from a simple state → IANA map (NV → America/Los_Angeles,
NY → America/New_York, etc.) and hardcode `start_time_local: "19:00"` (Phish's
canonical curtain). If phish.net adds explicit start_time later, wire it in.

**Step 1: Failing test** (fixture stubs phish.net via httpx_mock, plus the
`seeded_client` already in conftest provides a FastAPI client)

```python
from pytest_httpx import HTTPXMock

def test_upcoming_returns_next_phish_with_tz(httpx_mock: HTTPXMock, client):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=asc",
        json={"data": [
            {"showid": 2, "showdate": "2026-04-23", "artist_name": "Phish",
             "venue": "Sphere", "city": "Las Vegas", "state": "NV"},
        ]},
    )
    r = client.get("/upcoming")
    assert r.status_code == 200
    assert r.json() == {
        "show_id": 2,
        "show_date": "2026-04-23",
        "venue": "Sphere",
        "city": "Las Vegas",
        "state": "NV",
        "timezone": "America/Los_Angeles",
        "start_time_local": "19:00",
    }


def test_upcoming_404s_when_no_future_shows(httpx_mock, client):
    httpx_mock.add_response(json={"data": []})
    r = client.get("/upcoming")
    assert r.status_code == 404
```

Fixture note: `client` here is a lightweight `TestClient(create_app())`.
If `seeded_client` already provides this, reuse it; otherwise add a `client`
fixture to `conftest.py` with a minimal config (api key from env or fixed).

**Step 2:** Run — failure.

**Step 3: Implement**

New file `api/src/phishpicker/venue_tz.py`:
```python
"""Map US state codes to IANA timezones for Phish venues we care about.

Phish plays a bounded set of venues; fallback to America/New_York is fine
because (a) it's the dominant region and (b) any mis-mapping is a cosmetic
countdown bug, not a correctness issue.
"""
_STATE_TZ = {
    "NV": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "AZ": "America/Phoenix",
    "CO": "America/Denver",
    "UT": "America/Denver",
    "TX": "America/Chicago",
    "IL": "America/Chicago",
    # ...fill in as needed; default below catches the rest
}


def tz_for_state(state: str) -> str:
    return _STATE_TZ.get((state or "").upper(), "America/New_York")
```

In `app.py`, in the lifespan function, instantiate the phish.net client:
```python
from phishpicker.phishnet.client import PhishNetClient
app.state.phishnet_client = PhishNetClient(api_key=settings.phishnet_api_key)
```
Add a shutdown path to close it: either wrap the yield with try/finally or
call `close()` inside the `@asynccontextmanager` after the yield.

Endpoint:
```python
from datetime import datetime
from zoneinfo import ZoneInfo
from phishpicker.venue_tz import tz_for_state

@app.get("/upcoming")
def upcoming(request: Request):
    # "today" must be computed in a timezone that at least agrees with
    # the venue's local date — safer to use UTC and let /upcoming return
    # future-by-date. Phish's ticker is date-precision anyway.
    today = datetime.now(ZoneInfo("UTC")).date().isoformat()
    shows = request.app.state.phishnet_client.fetch_upcoming_shows(today)
    if not shows:
        raise HTTPException(status_code=404, detail="no upcoming Phish shows")
    first = shows[0]
    state = first.get("state", "")
    return {
        "show_id": int(first["showid"]),
        "show_date": first["showdate"],
        "venue": first.get("venue", ""),
        "city": first.get("city", ""),
        "state": state,
        "timezone": tz_for_state(state),
        "start_time_local": "19:00",
    }
```

**Step 4:** Run — pass.

**Step 5: Commit**
```bash
git commit -am "feat(api): /upcoming — next Phish show with timezone + start time"
```

---

### Task 4: Refactor `predict_next` to accept optional `played_songs`

Makes the predictor composable for the preview loop and for the new stateless
`POST /predict` endpoint.

**Files:**
- Modify: `api/src/phishpicker/predict.py`
- Create: `api/tests/test_predict_virtual_played.py`

**Step 1: Failing test**

```python
def test_predict_next_accepts_virtual_played(seeded_read_db):
    """When played_songs is passed explicitly, live DB lookup is bypassed."""
    from phishpicker.predict import predict_next
    # With virtual_played, no live_show_id is required — pass None + a
    # context kwargs dict:
    from phishpicker.predict import predict_next_stateless
    result = predict_next_stateless(
        read_conn=seeded_read_db,
        played_songs=[],
        current_set="1",
        show_date="2026-04-23",
        venue_id=1597,
        prev_trans_mark=",",
        prev_set_number=None,
        top_n=5,
    )
    assert len(result) <= 5
    assert all("song_id" in r and "name" in r for r in result)


def test_predict_next_virtual_excludes_previously_played(seeded_read_db):
    from phishpicker.predict import predict_next_stateless
    first = predict_next_stateless(
        read_conn=seeded_read_db, played_songs=[],
        current_set="1", show_date="2026-04-23", venue_id=1597,
        prev_trans_mark=",", prev_set_number=None, top_n=3,
    )
    top_id = first[0]["song_id"]
    second = predict_next_stateless(
        read_conn=seeded_read_db, played_songs=[top_id],
        current_set="1", show_date="2026-04-23", venue_id=1597,
        prev_trans_mark=",", prev_set_number="1", top_n=3,
    )
    assert top_id not in [r["song_id"] for r in second]
```

Need a `seeded_read_db` fixture. Check conftest; if absent, add a small
fixture that applies `schema.sql` + inserts a handful of songs + one show.

**Step 2:** Run — failure.

**Step 3: Extract `predict_next_stateless`**

Refactor `predict.py`:

```python
def predict_next_stateless(
    *,
    read_conn: sqlite3.Connection,
    played_songs: list[int],
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str = ",",
    prev_set_number: str | None = None,
    top_n: int = 20,
    scorer: Scorer | None = None,
) -> list[dict]:
    """Pure prediction over an explicit played list — no live DB."""
    if scorer is None:
        scorer = HeuristicScorer()

    song_ids = [r["song_id"] for r in read_conn.execute(
        "SELECT song_id FROM songs"
    ).fetchall()]
    if not song_ids:
        return []

    scored = scorer.score_candidates(
        conn=read_conn,
        show_date=show_date,
        venue_id=venue_id,
        played_songs=played_songs,
        current_set=current_set,
        candidate_song_ids=song_ids,
        prev_trans_mark=prev_trans_mark,
        prev_set_number=prev_set_number,
    )
    scored = apply_post_rules(scored, played_tonight=set(played_songs))
    scored = [(sid, s) for sid, s in scored if s > 0.0]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = scored[:top_n]
    total = sum(s for _, s in top) or 1.0
    normalized = [(sid, s, s / total) for sid, s in top]

    top_ids = [sid for sid, _, _ in normalized]
    names = (
        dict(read_conn.execute(
            f"SELECT song_id, name FROM songs WHERE song_id IN ({','.join('?' * len(top_ids))})",
            top_ids,
        ).fetchall()) if top_ids else {}
    )
    return [
        {"song_id": sid, "name": names.get(sid, f"#{sid}"),
         "score": s, "probability": p}
        for sid, s, p in normalized
    ]
```

Then refactor `predict_next` to read played from the live DB and delegate:

```python
def predict_next(
    read_conn, live_conn, live_show_id, top_n=20, scorer=None,
) -> list[dict]:
    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (live_show_id,),
    ).fetchone()
    if not show:
        return []
    played = live_conn.execute(
        "SELECT song_id, entered_order, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (live_show_id,),
    ).fetchall()
    return predict_next_stateless(
        read_conn=read_conn,
        played_songs=[r["song_id"] for r in played],
        current_set=show["current_set"],
        show_date=show["show_date"],
        venue_id=show["venue_id"],
        prev_trans_mark=played[-1]["trans_mark"] if played else ",",
        prev_set_number=played[-1]["set_number"] if played else None,
        top_n=top_n,
        scorer=scorer,
    )
```

**Step 4:** Run all tests — pre-existing `predict_next` tests must still pass.

**Step 5: Commit**
```bash
git commit -am "refactor(predict): extract predict_next_stateless; predict_next delegates"
```

---

### Task 5: `POST /predict` endpoint

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Create: `api/tests/test_predict_post.py`

**Step 1: Failing test**

```python
def test_post_predict_returns_top_k_from_played(client):
    r = client.post("/predict", json={
        "played_songs": [],
        "current_set": "1",
        "show_date": "2026-04-23",
        "venue_id": 1597,
        "top_n": 5,
    })
    assert r.status_code == 200
    data = r.json()["candidates"]
    assert len(data) <= 5


def test_post_predict_excludes_played(client):
    first = client.post("/predict", json={
        "played_songs": [], "current_set": "1",
        "show_date": "2026-04-23", "venue_id": 1597, "top_n": 3,
    }).json()["candidates"]
    top_id = first[0]["song_id"]
    second = client.post("/predict", json={
        "played_songs": [top_id], "current_set": "1",
        "show_date": "2026-04-23", "venue_id": 1597, "top_n": 3,
        "prev_set_number": "1",
    }).json()["candidates"]
    assert top_id not in [c["song_id"] for c in second]
```

**Step 2:** Run — failure.

**Step 3: Implement**

```python
class PredictRequest(BaseModel):
    played_songs: list[int] = []
    current_set: str
    show_date: str
    venue_id: int | None = None
    prev_trans_mark: str = ","
    prev_set_number: str | None = None
    top_n: int = 20

@app.post("/predict")
def predict_post(
    body: PredictRequest,
    request: Request,
    read: sqlite3.Connection = Depends(get_read),
):
    from phishpicker.predict import predict_next_stateless
    return {"candidates": predict_next_stateless(
        read_conn=read, scorer=request.app.state.scorer,
        **body.model_dump(),
    )}
```

**Step 4:** Pass.

**Step 5: Commit**
```bash
git commit -am "feat(api): POST /predict — stateless prediction endpoint"
```

---

### Task 6: `/live/show/{show_id}/preview` — loop over `/predict`

Now that prediction is stateless, the preview is a straightforward loop:
load played from live DB, default structure from `live_show_meta`, loop
through slots, extending the virtual played list with top-1 each step.

**Files:**
- Create: `api/src/phishpicker/live_preview.py`
- Modify: `api/src/phishpicker/app.py`
- Create: `api/tests/test_live_preview.py`

**Step 1: Failing tests**

```python
def test_preview_default_972_structure(client, live_show_id):
    r = client.get(f"/live/show/{live_show_id}/preview")
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert len(slots) == 18
    sets = [s["set_number"] for s in slots]
    assert sets.count("1") == 9 and sets.count("2") == 7 and sets.count("E") == 2


def test_preview_marks_entered_slots(client, live_show_with_one_song):
    r = client.get(f"/live/show/{live_show_with_one_song['show_id']}/preview")
    slots = r.json()["slots"]
    assert slots[0]["state"] == "entered"
    assert slots[0]["entered_song"]["song_id"] == live_show_with_one_song["song_id"]
    assert slots[1]["state"] == "predicted"


def test_preview_each_predicted_slot_has_top_k():
    # same as above; check top_k length == 10 by default
    ...


def test_preview_respects_live_show_meta_sizes(client, live_show_id):
    # write custom sizes via POST /live/show/{id}/structure; preview respects them
    client.post(f"/live/show/{live_show_id}/structure",
                json={"set1": 10, "set2": 8, "encore": 3})
    r = client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    assert len(slots) == 21
```

**Step 2:** Run — failure.

**Step 3: Implement `live_preview.py`**

```python
"""Stateless preview builder — loops predict_next_stateless."""

import sqlite3
from phishpicker.predict import predict_next_stateless


def build_preview(
    *,
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    top_k: int,
    scorer,
) -> dict:
    from fastapi import HTTPException
    show = live_conn.execute(
        "SELECT show_date, venue_id FROM live_show WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if not show:
        raise HTTPException(404, "show not found")
    meta = live_conn.execute(
        "SELECT set1_size, set2_size, encore_size FROM live_show_meta WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if meta is None:
        set1, set2, enc = 9, 7, 2
    else:
        set1, set2, enc = meta["set1_size"], meta["set2_size"], meta["encore_size"]

    played_rows = live_conn.execute(
        "SELECT song_id, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (show_id,),
    ).fetchall()
    played_names = dict(read_conn.execute(
        "SELECT song_id, name FROM songs"
    ).fetchall()) if played_rows else {}

    # bucket played songs by (set_number, position)
    entered_by_pos: dict[tuple[str, int], dict] = {}
    per_set_seen: dict[str, int] = {}
    for r in played_rows:
        per_set_seen[r["set_number"]] = per_set_seen.get(r["set_number"], 0) + 1
        entered_by_pos[(r["set_number"], per_set_seen[r["set_number"]])] = {
            "song_id": r["song_id"],
            "name": played_names.get(r["song_id"], f"#{r['song_id']}"),
        }

    virtual_played: list[int] = [r["song_id"] for r in played_rows]
    prev_trans_mark = played_rows[-1]["trans_mark"] if played_rows else ","
    prev_set_number: str | None = played_rows[-1]["set_number"] if played_rows else None

    structure = [("1", set1), ("2", set2), ("E", enc)]
    slots = []
    slot_idx = 0
    for set_number, n in structure:
        for pos in range(1, n + 1):
            slot_idx += 1
            entered = entered_by_pos.get((set_number, pos))
            if entered:
                slots.append({
                    "slot_idx": slot_idx,
                    "set_number": set_number,
                    "position": pos,
                    "state": "entered",
                    "entered_song": entered,
                })
                continue
            cands = predict_next_stateless(
                read_conn=read_conn,
                played_songs=virtual_played,
                current_set=set_number,
                show_date=show["show_date"],
                venue_id=show["venue_id"],
                prev_trans_mark=prev_trans_mark,
                prev_set_number=prev_set_number,
                top_n=top_k,
                scorer=scorer,
            )
            slots.append({
                "slot_idx": slot_idx,
                "set_number": set_number,
                "position": pos,
                "state": "predicted",
                "top_k": [{**c, "rank": i + 1} for i, c in enumerate(cands)],
            })
            if cands:
                virtual_played = virtual_played + [cands[0]["song_id"]]
                prev_trans_mark = ","
                prev_set_number = set_number
    return {"slots": slots}
```

Endpoint:
```python
@app.get("/live/show/{show_id}/preview")
def preview_endpoint(
    show_id: str, request: Request, top_k: int = 10,
    read: sqlite3.Connection = Depends(get_read),
    live: sqlite3.Connection = Depends(get_live),
):
    from phishpicker.live_preview import build_preview
    return build_preview(
        read_conn=read, live_conn=live, show_id=show_id,
        top_k=top_k, scorer=request.app.state.scorer,
    )
```

**Step 4: Add `POST /live/show/{show_id}/structure`**

```python
class StructureUpdate(BaseModel):
    set1: int = 9
    set2: int = 7
    encore: int = 2

@app.post("/live/show/{show_id}/structure")
def set_structure(show_id: str, body: StructureUpdate,
                  live: sqlite3.Connection = Depends(get_live)):
    live.execute(
        "INSERT INTO live_show_meta (show_id, set1_size, set2_size, encore_size) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(show_id) DO UPDATE SET "
        "set1_size=excluded.set1_size, set2_size=excluded.set2_size, encore_size=excluded.encore_size",
        (show_id, body.set1, body.set2, body.encore),
    )
    live.commit()
    return {"ok": True}
```

**Step 5:** Pass.

**Step 6: Commit**
```bash
git commit -am "feat(api): /live/show/{id}/preview + /structure — stateless full preview"
```

---

### Task 7: `/live/show/{show_id}/slot/{idx}/alternatives`

Thin wrapper over `build_preview` that returns a single slot.

**Step 1: Test**
```python
def test_slot_alternatives_returns_single_slot(client, live_show_id):
    r = client.get(f"/live/show/{live_show_id}/slot/5/alternatives?top_k=5")
    assert r.status_code == 200
    s = r.json()
    assert s["slot_idx"] == 5
    assert s["state"] == "predicted"
    assert len(s["top_k"]) == 5
```

**Step 2-4: Implement + pass**

```python
@app.get("/live/show/{show_id}/slot/{slot_idx}/alternatives")
def slot_alternatives(
    show_id: str, slot_idx: int, request: Request, top_k: int = 10,
    read: sqlite3.Connection = Depends(get_read),
    live: sqlite3.Connection = Depends(get_live),
):
    from phishpicker.live_preview import build_preview
    pr = build_preview(read_conn=read, live_conn=live, show_id=show_id,
                        top_k=top_k, scorer=request.app.state.scorer)
    if slot_idx < 1 or slot_idx > len(pr["slots"]):
        raise HTTPException(404)
    return pr["slots"][slot_idx - 1]
```

**Step 5: Commit**
`feat(api): /live/show/{id}/slot/{idx}/alternatives`

---

### Task 8: `POST /songs` bustout insertion

**Files:**
- Modify: `app.py` (+ new dep factory)
- Create: `api/tests/test_bustout_insert.py`

**Step 1: Test**

```python
def test_post_songs_inserts_bustout(client):
    r = client.post("/songs", json={"name": "Mystery Cover"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Mystery Cover"
    assert body["is_bustout_placeholder"] is True
    assert isinstance(body["song_id"], int)
    # idempotent on duplicate
    r2 = client.post("/songs", json={"name": "Mystery Cover"})
    assert r2.status_code == 200
    assert r2.json()["song_id"] == body["song_id"]
```

**Step 2-4: Implement**

Add a new dep factory in `app.py`:
```python
def _read_write_conn_dep(settings: Settings) -> Iterator[sqlite3.Connection]:
    def _dep() -> Iterator[sqlite3.Connection]:
        with closing(open_db(settings.db_path, read_only=False)) as c:
            yield c
    return _dep

get_rw = _read_write_conn_dep(settings)
app.state.get_rw = get_rw
```

Endpoint:
```python
class NewSong(BaseModel):
    name: str

@app.post("/songs", status_code=201)
def insert_song(body: NewSong, response: Response,
                 conn: sqlite3.Connection = Depends(get_rw)):
    existing = conn.execute(
        "SELECT song_id, name, is_bustout_placeholder FROM songs WHERE name = ?",
        (body.name,),
    ).fetchone()
    if existing:
        response.status_code = 200
        return {"song_id": existing["song_id"], "name": existing["name"],
                "is_bustout_placeholder": bool(existing["is_bustout_placeholder"])}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cur = conn.execute(
        "INSERT INTO songs (name, first_seen_at, is_bustout_placeholder) "
        "VALUES (?, ?, 1)",
        (body.name, now),
    )
    conn.commit()
    return {"song_id": cur.lastrowid, "name": body.name, "is_bustout_placeholder": True}
```

**Step 5: Commit**
`feat(api): POST /songs — insert bustout placeholder`

---

## Phase 2 — Phish.net live sync

### Task 9: `reconcile` pure function

**Files:**
- Create: `api/src/phishpicker/live_sync.py`
- Create: `api/tests/test_live_sync_reconcile.py`

**Step 1: Tests** (5 cases from the design's reconciliation table)

```python
from phishpicker.live_sync import reconcile, ReconcileAction

def _u(sid, s="1"): return {"song_id": sid, "set_number": s}

def test_append_when_net_ahead():
    actions = reconcile([_u(1), _u(2)], [_u(1), _u(2), _u(3), _u(4)])
    assert [a.kind for a in actions] == ["append", "append"]
    assert actions[0].song_id == 3

def test_noop_when_aligned():
    assert reconcile([_u(1), _u(2)], [_u(1), _u(2)]) == []

def test_noop_when_user_ahead():
    assert reconcile([_u(1), _u(2), _u(3)], [_u(1), _u(2)]) == []

def test_override_on_mismatch():
    actions = reconcile([_u(1), _u(99)], [_u(1), _u(2)])
    assert len(actions) == 1
    assert actions[0].kind == "override"
    assert actions[0].slot_idx == 2
    assert actions[0].old_song_id == 99
    assert actions[0].song_id == 2

def test_append_with_bustout_flag():
    actions = reconcile([], [{"song_id": 5, "set_number": "1", "is_unknown": True}])
    assert actions[0].kind == "append"
    assert actions[0].is_bustout is True
```

**Step 2-4: Implement** (same as the v1 plan — pure function)

```python
from dataclasses import dataclass


@dataclass
class ReconcileAction:
    kind: str  # "append" | "override"
    slot_idx: int
    song_id: int
    set_number: str
    old_song_id: int | None = None
    is_bustout: bool = False


def reconcile(user_rows, net_rows) -> list[ReconcileAction]:
    actions: list[ReconcileAction] = []
    for i in range(len(net_rows)):
        net = net_rows[i]
        if i >= len(user_rows):
            actions.append(ReconcileAction(
                kind="append", slot_idx=i + 1,
                song_id=net["song_id"], set_number=net["set_number"],
                is_bustout=bool(net.get("is_unknown"))))
            continue
        user = user_rows[i]
        if user["song_id"] == net["song_id"]:
            continue
        actions.append(ReconcileAction(
            kind="override", slot_idx=i + 1,
            song_id=net["song_id"], set_number=net["set_number"],
            old_song_id=user["song_id"],
            is_bustout=bool(net.get("is_unknown"))))
    return actions
```

**Step 5: Commit**
`feat(live-sync): reconcile — pure user-vs-phishnet diff logic`

---

### Task 10: `replace_song_at` DB helper (supports interior override)

**Files:**
- Modify: `api/src/phishpicker/live.py`
- Modify: `api/tests/test_live.py` (or create it if absent)

**Step 1: Test**

```python
def test_replace_song_at_updates_in_place(live_conn, seeded_live_show):
    from phishpicker.live import append_song, replace_song_at
    sid = seeded_live_show
    append_song(live_conn, sid, song_id=1, set_number="1")
    append_song(live_conn, sid, song_id=2, set_number="1")
    append_song(live_conn, sid, song_id=3, set_number="1")
    ok = replace_song_at(live_conn, sid, entered_order=2, new_song_id=99,
                        source="phishnet", superseded_by=2)
    assert ok is True
    rows = live_conn.execute(
        "SELECT song_id, source, superseded_by FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order", (sid,),
    ).fetchall()
    assert rows[1]["song_id"] == 99
    assert rows[1]["source"] == "phishnet"
    assert rows[1]["superseded_by"] == 2
```

**Step 2-4: Implement**

```python
def replace_song_at(
    conn: sqlite3.Connection, show_id: str,
    entered_order: int, new_song_id: int,
    source: str = "phishnet", superseded_by: int | None = None,
) -> bool:
    cur = conn.execute(
        "UPDATE live_songs SET song_id = ?, source = ?, superseded_by = ? "
        "WHERE show_id = ? AND entered_order = ?",
        (new_song_id, source, superseded_by, show_id, entered_order),
    )
    conn.commit()
    return cur.rowcount > 0
```

**Step 5: Commit**
`feat(live): replace_song_at — interior-slot override helper`

---

### Task 11: `sync_show_with_phishnet`

**Files:**
- Modify: `api/src/phishpicker/live_sync.py`
- Create: `api/tests/test_sync_show.py`

**Step 1: Test** (exercises append + override via httpx_mock)

```python
def test_sync_appends_net_rows(httpx_mock, live_setup):
    from phishpicker.live_sync import sync_show_with_phishnet
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={"data": [
            {"songid": 1, "song": "A", "set": "1", "position": 1, "artist_name": "Phish"},
            {"songid": 2, "song": "B", "set": "1", "position": 2, "artist_name": "Phish"},
        ]},
    )
    result = sync_show_with_phishnet(
        db_path=live_setup.db_path, live_db_path=live_setup.live_db_path,
        api_key="k", show_id=live_setup.show_id, show_date="2026-04-23",
    )
    assert result == {"appended": 2, "overrides": 0, "bustouts": 0,
                      "status": "ok", "last_updated": ...}
```

**Step 2-4: Implement**

```python
from datetime import datetime, timezone
from phishpicker.db.connection import open_db
from phishpicker.live import (
    append_song, get_live_show, replace_song_at,
)
from phishpicker.phishnet.client import PhishNetClient


def sync_show_with_phishnet(
    *, db_path, live_db_path, api_key: str,
    show_id: str, show_date: str,
) -> dict:
    """Idempotent reconcile of live_songs with phish.net's current setlist.

    Opens its OWN connections each call — this function is safe to call
    from an asyncio worker thread; do NOT pass connections in.
    """
    with PhishNetClient(api_key) as client:
        net_raw = client.fetch_setlist_by_date(show_date)

    with open_db(db_path, read_only=False) as read_rw, open_db(live_db_path) as live:
        # Resolve phish.net songid → our song_id, inserting bustouts as needed.
        net_rows: list[dict] = []
        for r in net_raw:
            sid = _resolve_or_insert_song(read_rw, r)
            net_rows.append({
                "song_id": sid["song_id"],
                "set_number": str(r["set"]).upper(),
                "is_unknown": sid["is_unknown"],
            })

        live_show = get_live_show(live, show_id)
        if not live_show:
            return {"status": "no-show", "appended": 0, "overrides": 0, "bustouts": 0}

        user_rows = [
            {"song_id": s["song_id"], "set_number": s["set_number"]}
            for s in live_show["songs"]
        ]
        actions = reconcile(user_rows, net_rows)

        appended = overrides = bustouts = 0
        for a in actions:
            if a.kind == "append":
                append_song(live, show_id, a.song_id, a.set_number)
                appended += 1
            else:  # override
                # slot_idx is 1-indexed; entered_order matches 1-indexed insertion order
                replace_song_at(live, show_id, entered_order=a.slot_idx,
                                 new_song_id=a.song_id,
                                 source="phishnet", superseded_by=a.old_song_id)
                overrides += 1
            if a.is_bustout:
                bustouts += 1

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        live.execute(
            "INSERT INTO live_show_meta (show_id, last_updated, last_error) "
            "VALUES (?, ?, NULL) "
            "ON CONFLICT(show_id) DO UPDATE SET "
            "last_updated=excluded.last_updated, last_error=NULL",
            (show_id, now),
        )
        live.commit()

    return {"status": "ok", "appended": appended, "overrides": overrides,
            "bustouts": bustouts, "last_updated": now}


def _resolve_or_insert_song(read_conn, net_row: dict) -> dict:
    """Find a local song_id for a phish.net song; insert a bustout placeholder
    if the name is unknown. Returns {"song_id": int, "is_unknown": bool}."""
    name = net_row.get("song", "")
    row = read_conn.execute(
        "SELECT song_id, is_bustout_placeholder FROM songs WHERE name = ?",
        (name,),
    ).fetchone()
    if row:
        return {"song_id": row["song_id"], "is_unknown": bool(row["is_bustout_placeholder"])}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cur = read_conn.execute(
        "INSERT INTO songs (name, first_seen_at, is_bustout_placeholder) "
        "VALUES (?, ?, 1)", (name, now),
    )
    read_conn.commit()
    return {"song_id": cur.lastrowid, "is_unknown": True}
```

**Step 5: Commit**
`feat(live-sync): sync_show_with_phishnet — full reconcile with interior overrides + bustout insert`

---

### Task 12: `PollerRegistry` on `app.state`

**Files:**
- Modify: `api/src/phishpicker/live_sync.py`
- Modify: `api/src/phishpicker/app.py` (lifespan)
- Modify: `api/tests/conftest.py` (teardown fixture)
- Create: `api/tests/test_poller.py`

**Step 1: Test**

```python
import asyncio
import pytest

@pytest.mark.asyncio
async def test_poller_registry_runs_sync_on_interval(monkeypatch):
    from phishpicker.live_sync import PollerRegistry
    calls = []
    async def fake_sync(*, show_id, show_date, **kw):
        calls.append((show_id, show_date))
    reg = PollerRegistry(sync_fn=fake_sync)
    await reg.start("abc", show_date="2026-04-23", interval=0.05)
    await asyncio.sleep(0.12)
    await reg.stop("abc")
    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_poller_registry_stop_is_idempotent():
    from phishpicker.live_sync import PollerRegistry
    reg = PollerRegistry()
    await reg.stop("nothing")  # must not raise


@pytest.mark.asyncio
async def test_poller_registry_start_idempotent_for_same_show():
    from phishpicker.live_sync import PollerRegistry
    calls = []
    async def s(**kw): calls.append(1)
    reg = PollerRegistry(sync_fn=s)
    await reg.start("a", show_date="x", interval=1)
    await reg.start("a", show_date="x", interval=1)  # no-op
    assert len(reg._tasks) == 1
    await reg.stop("a")
```

Add to conftest:
```python
@pytest.fixture(autouse=True)
async def _cancel_pollers_teardown(request):
    yield
    # Best-effort: if any test touched app.state.pollers, cancel its tasks.
    ...
```

**Step 2-4: Implement**

```python
import asyncio
import logging
from collections.abc import Callable

log = logging.getLogger(__name__)


class PollerRegistry:
    def __init__(self, sync_fn: Callable | None = None):
        self._tasks: dict[str, asyncio.Task] = {}
        self._meta: dict[str, dict] = {}  # show_id -> {"last_error": str|None}
        self._sync_fn = sync_fn or _default_sync

    async def start(self, show_id: str, show_date: str, interval: float = 60.0,
                    **sync_kwargs):
        if show_id in self._tasks and not self._tasks[show_id].done():
            return
        self._tasks[show_id] = asyncio.create_task(
            self._loop(show_id, show_date, interval, sync_kwargs)
        )

    async def stop(self, show_id: str):
        task = self._tasks.pop(show_id, None)
        if task and not task.done():
            task.cancel()

    async def stop_all(self):
        for sid in list(self._tasks):
            await self.stop(sid)

    def last_error(self, show_id: str) -> str | None:
        return self._meta.get(show_id, {}).get("last_error")

    async def _loop(self, show_id, show_date, interval, sync_kwargs):
        while True:
            try:
                await self._sync_fn(show_id=show_id, show_date=show_date, **sync_kwargs)
                self._meta.setdefault(show_id, {})["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("sync failed for %s: %s", show_id, e)
                self._meta.setdefault(show_id, {})["last_error"] = str(e)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise


async def _default_sync(*, show_id, show_date, db_path, live_db_path, api_key):
    await asyncio.to_thread(
        sync_show_with_phishnet,
        db_path=db_path, live_db_path=live_db_path,
        api_key=api_key, show_id=show_id, show_date=show_date,
    )
```

In `app.py` lifespan:
```python
app.state.pollers = PollerRegistry()
```
And in teardown: `await app.state.pollers.stop_all()`.

**Step 5: Commit**
`feat(live-sync): PollerRegistry — app-state-scoped, test-isolated`

---

### Task 13: `/live/show/{id}/sync/start|stop|status` endpoints

```python
@app.post("/live/show/{show_id}/sync/start")
async def sync_start(show_id: str, body: dict, request: Request,
                     live: sqlite3.Connection = Depends(get_live)):
    show_date = body["show_date"]
    settings = request.app.state.settings
    await request.app.state.pollers.start(
        show_id, show_date=show_date, interval=60.0,
        db_path=settings.db_path, live_db_path=settings.live_db_path,
        api_key=settings.phishnet_api_key,
    )
    live.execute(
        "INSERT INTO live_show_meta (show_id, sync_enabled) VALUES (?, 1) "
        "ON CONFLICT(show_id) DO UPDATE SET sync_enabled=1",
        (show_id,),
    )
    live.commit()
    return {"started": True}

@app.post("/live/show/{show_id}/sync/stop")
async def sync_stop(show_id: str, request: Request,
                    live: sqlite3.Connection = Depends(get_live)):
    await request.app.state.pollers.stop(show_id)
    live.execute(
        "UPDATE live_show_meta SET sync_enabled=0 WHERE show_id = ?", (show_id,),
    )
    live.commit()
    return {"stopped": True}

@app.get("/live/show/{show_id}/sync/status")
def sync_status(show_id: str, request: Request,
                live: sqlite3.Connection = Depends(get_live)):
    row = live.execute(
        "SELECT sync_enabled, last_updated, last_error FROM live_show_meta "
        "WHERE show_id = ?", (show_id,),
    ).fetchone()
    if not row:
        return {"state": "off", "sync_enabled": False, "last_updated": None, "last_error": None}
    # Compute state bucket from last_updated
    from datetime import datetime, timezone as tz
    state = "off"
    if row["sync_enabled"]:
        if row["last_updated"]:
            last = datetime.fromisoformat(row["last_updated"].replace("Z", "+00:00"))
            age = (datetime.now(tz.utc) - last).total_seconds()
            if age < 120: state = "live"
            elif age < 600: state = "stale"
            else: state = "dead"
        else:
            state = "stale"
        if row["last_error"]:
            state = "dead"
    return {"state": state,
            "sync_enabled": bool(row["sync_enabled"]),
            "last_updated": row["last_updated"],
            "last_error": row["last_error"]}
```

**Tests + commit.** `feat(api): /live/show/{id}/sync/{start,stop,status}`

---

## Phase 3 — Frontend

### Task 14: ShowHeader + timezone-aware countdown

- Component in `web/src/components/ShowHeader.tsx` + test using `screen.*`.
- Uses `Intl.DateTimeFormat().resolvedOptions().timeZone` for browser TZ.
- Computes `hoursUntilShow(browserNow, showDate, showStartLocal, showTz)` as a
  pure function in `web/src/lib/time.ts` with its own tests.

`feat(web): ShowHeader + timezone-aware countdown`

### Task 15: Auto-load next show

- Modify `page.tsx` to replace "Start show" button with SWR-fetched
  `/upcoming`, auto-starting the show via `useLiveShow.startShow(show_date)`.
- SWR config: `{revalidateOnFocus: false, dedupingInterval: 60_000}`.

`feat(web): auto-load next Phish show`

### Task 16: FullPreview component

- `web/src/components/FullPreview.tsx` + test with `screen.getAllByTestId("slot")`.
- SWR hook in `web/src/lib/preview.ts` fetching `/api/live/show/{id}/preview`.
- Refreshes on played-song changes (pass `refreshTrigger` counter or use SWR
  key that includes `playedSongs.length`).

`feat(web): FullPreview component + SWR hook`

### Task 17: SlotAltsModal

- Bottom-sheet modal, mobile-first.
- Hits `/api/live/show/{id}/slot/{idx}/alternatives`.
- Integrated in `page.tsx` as `onSlotClick` handler.

`feat(web): SlotAltsModal`

### Task 18: SyncStatus pill + toggle

- `web/src/components/SyncStatus.tsx`.
- Polls `/api/live/show/{id}/sync/status` every 5s.
- POST start/stop on tap.

`feat(web): SyncStatus pill + toggle`

### Task 19: Bustout flow in SongSearch

- Modify `SongSearch.tsx` + test: when 0 matches, offer "Add '$query' as new song."
- On confirm, POST `/api/songs` then call `onAdd` with the returned song.

`feat(web): SongSearch bustout add flow`

### Task 20: Integrate in `page.tsx`

- Replace existing single-"Next song" Leaderboard with FullPreview + SlotAltsModal.
- Add ShowHeader, SyncStatus at top.
- Page.test.tsx asserts composition.

`feat(web): integrate header/preview/sync in main page`

---

## Phase 4 — Deploy

### Task 21: Local integration run

Boot api + web locally; walk through a fake show manually; fix visual/logic
bugs found. Commits as they come.

### Task 22: Deploy to NAS

`scripts/deploy_to_nas.sh` or equivalent. Verify Cloudflare tunnel. Test on phone.

Update `docs/plans/RESUME.md` with deploy status.

---

## Summary

**22 tasks.** Phase 1: 9 tasks (~6h), Phase 2: 5 tasks (~4h), Phase 3: 7 tasks
(~6h with Next.js 16 caveat buffer), Phase 4: 2 tasks (~2h).

**Critical path for Night 4 (Thu 4/23):** Phases 1-2 + frontend Task 15 + 18
(auto-load + sync pill). That's the minimum that makes the phone picker
useful during a remotely-watched show.

**Full ship for Night 7 (Thu 4/30):** All 22 tasks.
