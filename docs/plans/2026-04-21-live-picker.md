# Live Picker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the existing `web/` Next.js app and `api/` FastAPI backend with a
live-during-a-Phish-show UI: auto-load tonight's show, display a grayed-out
predicted setlist (9/7/2 default), show per-slot top-10 alternatives, typeahead
song entry, undo stack, set transitions, bustout handling, and background
phish.net reconciliation so the user doesn't have to enter every song.

**Architecture:** Builds on existing FastAPI `/live/*` endpoints (in
`api/src/phishpicker/app.py`) and existing React components (`Leaderboard`,
`SongSearch`, `AddSongSheet`, `PlayedStrip`, `SetBoundaryButton`). New
backend endpoints live in `api/src/phishpicker/app.py` for small additions
and `api/src/phishpicker/live_sync.py` for the phish.net poller. New React
components live beside existing ones.

**Tech Stack:** Python 3.12 / FastAPI / sqlite3 / httpx · Next.js 16 / React
19 / TypeScript / Tailwind 4 / SWR / fuse.js / Vitest.

**Design doc:** `docs/plans/2026-04-21-live-picker-design.md`

**Testing commands:**
- Backend: `cd api && uv run pytest -q`
- Frontend: `cd web && npm test`
- Lint backend: `cd api && uv run ruff check src tests`
- Lint frontend: `cd web && npm run lint`

**⚠ Next.js 16 caveat:** `web/AGENTS.md` warns that Next 16 has breaking
changes and APIs may differ from training data. Before writing any Next
server code (route handlers, metadata, middleware), read
`node_modules/next/dist/docs/` for the relevant API. Existing code in this
repo is the authoritative reference for conventions.

---

## Existing code reference (what we're extending)

Backend endpoints (`api/src/phishpicker/app.py`):
- `GET /meta`, `GET /about`, `GET /songs`, `GET /predict/{show_id}`
- `POST /live/show`, `GET /live/show/{show_id}`, `POST /live/song`,
  `DELETE /live/song/last`, `POST /live/set-boundary`
- `POST /internal/reload`

Backend modules:
- `api/src/phishpicker/live.py` — `create_live_show`, `append_song`,
  `delete_last_song`, `advance_set`, `get_live_show`
- `api/src/phishpicker/predict.py` — `predict_next`
- `api/src/phishpicker/phishnet/client.py` — `PhishNetClient._get`,
  `.fetch_setlist`, `.fetch_songs`
- `api/src/phishpicker/nightly_smoke.py` — reference for
  `setlists/showdate/{date}.json` usage

Frontend (`web/src/`):
- `app/page.tsx` — main picker page
- `app/api/[...path]/route.ts` — transparent proxy to FastAPI (just hit
  `/api/foo` from the client and FastAPI gets `/foo`)
- `components/Leaderboard.tsx`, `SongSearch.tsx`, `AddSongSheet.tsx`,
  `PlayedStrip.tsx`, `SetBoundaryButton.tsx`
- `lib/liveShow.ts` — `useLiveShow` hook; state + API calls for live show
- `lib/songs.ts` — song cache

---

## Phase 1 — Backend foundations (upcoming show, venue lookup, schema)

### Task 1: Add `is_bustout_placeholder` column to `songs`

**Files:**
- Modify: `api/src/phishpicker/db/schema.sql` (line 15 area — songs table)
- Create: `api/src/phishpicker/db/migrations/0001_bustout_flag.sql`
- Modify: `api/src/phishpicker/db/connection.py` (ensure migrations run on
  `apply_schema`)

**Step 1: Failing test**

Add to `api/tests/test_db.py` (or new `test_schema.py` if no such file):
```python
import sqlite3
from phishpicker.db.connection import apply_schema

def test_songs_has_is_bustout_placeholder_column(tmp_path):
    import sqlite3
    conn = sqlite3.connect(":memory:")
    apply_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(songs)").fetchall()]
    assert "is_bustout_placeholder" in cols
```

**Step 2: Run — expect failure** (`cd api && uv run pytest tests/test_schema.py -v`)

**Step 3: Add column to schema.sql**

Append after the `songs` CREATE TABLE:
```sql
-- Bustout placeholders: songs manually added via the live picker when
-- phish.net hasn't surfaced them yet. Reconciled post-show against phish.net.
ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER NOT NULL DEFAULT 0;
```

Note: `CREATE TABLE IF NOT EXISTS` means we can't just edit the original
CREATE — add it as a separate `ALTER TABLE` that's idempotent via a guard,
or reset the DB in dev. Simplest: add an ALTER after the CREATE with a
try/except in code, OR edit the CREATE TABLE statement directly (the IF
NOT EXISTS means existing tables are untouched, but fresh dev DBs get the
column).

Preferred: edit the CREATE TABLE directly to add
`is_bustout_placeholder INTEGER NOT NULL DEFAULT 0` right before the
closing paren.

Then in `connection.py::apply_schema`, after the executescript, run:
```python
# Ensure is_bustout_placeholder exists on already-created DBs.
try:
    conn.execute("ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER NOT NULL DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    pass  # column already exists
```

**Step 4: Run — pass**

**Step 5: Commit**
```bash
git add api/src/phishpicker/db/schema.sql api/src/phishpicker/db/connection.py api/tests/test_schema.py
git commit -m "feat(schema): add is_bustout_placeholder column to songs"
```

---

### Task 2: Add `/upcoming` endpoint — next Phish show

**Files:**
- Modify: `api/src/phishpicker/app.py` (add endpoint + helper)
- Modify: `api/src/phishpicker/phishnet/client.py` (add method)
- Modify: `api/tests/test_app.py` (or create `test_upcoming.py`)

**Step 1: Failing test**

```python
# api/tests/test_upcoming.py
from pytest_httpx import HTTPXMock
# Mocks phish.net to return a list of future shows; asserts /upcoming returns
# the earliest one with date >= today.

def test_upcoming_returns_next_phish_show(httpx_mock: HTTPXMock, api_client):
    # stub phish.net: one past show, two future ones
    httpx_mock.add_response(url=..., json={"data": [
        {"showid": 1, "showdate": "2026-01-01", "venue": "Old", "city": "X", "state": "Y"},
        {"showid": 2, "showdate": "2026-04-23", "venue": "Sphere", "city": "Las Vegas", "state": "NV"},
        {"showid": 3, "showdate": "2026-04-24", "venue": "Sphere", "city": "Las Vegas", "state": "NV"},
    ]})
    r = api_client.get("/upcoming")
    assert r.status_code == 200
    body = r.json()
    assert body["show_id"] == 2
    assert body["show_date"] == "2026-04-23"
    assert body["venue"] == "Sphere"
    assert body["city"] == "Las Vegas"
    assert body["state"] == "NV"
```

You'll need an `api_client` fixture in `conftest.py` — check
`api/tests/conftest.py` for an existing one; use it, or add one that wraps
`TestClient(create_app())` with a PhishNetClient that reads from the mock.

**Step 2: Add `PhishNetClient.fetch_upcoming_shows`**

```python
def fetch_upcoming_shows(self, from_date: str) -> list[dict]:
    """Shows on/after from_date (YYYY-MM-DD), filtered to Phish."""
    data = self._get("shows.json", {"order_by": "showdate", "direction": "asc"})
    return [
        d for d in data
        if str(d.get("artist_name")) == "Phish"
        and str(d.get("showdate", "")) >= from_date
    ]
```

**Step 3: Add `/upcoming` endpoint to `app.py`**

```python
@app.get("/upcoming")
def upcoming(request: Request):
    from datetime import date
    client = request.app.state.phishnet_client
    today = date.today().isoformat()
    shows = client.fetch_upcoming_shows(today)
    if not shows:
        raise HTTPException(status_code=404, detail="no upcoming Phish shows")
    first = shows[0]
    return {
        "show_id": int(first["showid"]),
        "show_date": first["showdate"],
        "venue": first.get("venue", ""),
        "city": first.get("city", ""),
        "state": first.get("state", ""),
    }
```

You'll need to wire `app.state.phishnet_client` in the lifespan handler
— see `app.py:48-58`. Add:
```python
from phishpicker.phishnet.client import PhishNetClient
app.state.phishnet_client = PhishNetClient(api_key=settings.phishnet_api_key)
```

(Verify `settings.phishnet_api_key` exists — it's `PHISHNET_API_KEY` in
docker-compose.yml.)

**Step 4: Run — pass**

**Step 5: Commit**
```bash
git commit -am "feat(api): /upcoming — next Phish show from phish.net"
```

---

### Task 3: Add `/venue/{venue_id}` endpoint (fallback venue lookup)

Used when upcoming() returns a `venue_id` but no embedded city/state (phish.net
sometimes does, sometimes doesn't).

**Step 1: Failing test**

```python
def test_venue_endpoint_returns_city_state(api_client, populated_db):
    # populated_db has venue_id=1597 inserted as Sphere/Las Vegas/NV
    r = api_client.get("/venue/1597")
    assert r.status_code == 200
    assert r.json() == {"venue_id": 1597, "name": "Sphere", "city": "Las Vegas", "state": "NV", "country": None}

def test_venue_endpoint_404s_on_missing(api_client):
    r = api_client.get("/venue/99999")
    assert r.status_code == 404
```

**Step 2: Implement**

```python
@app.get("/venue/{venue_id}")
def venue(venue_id: int, conn: sqlite3.Connection = Depends(get_read)):
    row = conn.execute(
        "SELECT venue_id, name, city, state, country FROM venues WHERE venue_id = ?",
        (venue_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="venue not found")
    return dict(row)
```

**Step 3: Commit**
```bash
git commit -am "feat(api): /venue/{venue_id} — venue lookup"
```

---

### Task 4: Add `/live/show/{show_id}/preview` — full grayed setlist

Returns the model's autoregressive 9/7/2 preview (its top-1 for each slot,
treated as played forward to the next slot). Handles dynamic slot counts.

**Step 1: Failing test**

```python
def test_preview_returns_full_structure_default_972(api_client, live_show):
    # live_show is a fresh show with no songs
    r = api_client.get(f"/live/show/{live_show['show_id']}/preview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["slots"]) == 18  # 9 + 7 + 2
    set1 = [s for s in body["slots"] if s["set_number"] == "1"]
    set2 = [s for s in body["slots"] if s["set_number"] == "2"]
    enc = [s for s in body["slots"] if s["set_number"] == "E"]
    assert (len(set1), len(set2), len(enc)) == (9, 7, 2)
    # each slot has a predicted top-1
    assert body["slots"][0]["top_k"][0]["rank"] == 1


def test_preview_respects_structure_query_param(api_client, live_show):
    r = api_client.get(
        f"/live/show/{live_show['show_id']}/preview?set1=10&set2=8&encore=3"
    )
    body = r.json()
    assert sum(1 for s in body["slots"] if s["set_number"] == "1") == 10
    assert sum(1 for s in body["slots"] if s["set_number"] == "2") == 8
    assert sum(1 for s in body["slots"] if s["set_number"] == "E") == 3


def test_preview_marks_already_played_slots_as_entered(api_client, live_show_with_song):
    # live_show_with_song has one song appended to set 1
    r = api_client.get(f"/live/show/{live_show_with_song['show_id']}/preview")
    body = r.json()
    first_slot = body["slots"][0]
    assert first_slot["state"] == "entered"
    assert first_slot["entered_song"]["song_id"] == live_show_with_song["expected_song_id"]
```

**Step 2: Implement**

```python
@app.get("/live/show/{show_id}/preview")
def preview(
    show_id: str,
    request: Request,
    set1: int = 9,
    set2: int = 7,
    encore: int = 2,
    top_k: int = 10,
    read: sqlite3.Connection = Depends(get_read),
    live: sqlite3.Connection = Depends(get_live),
):
    from phishpicker.live_preview import build_preview
    return build_preview(read, live, show_id,
                         set1=set1, set2=set2, encore=encore, top_k=top_k,
                         scorer=request.app.state.scorer)
```

Create `api/src/phishpicker/live_preview.py`:

```python
"""Autoregressive full-show preview for a live show.

For each slot of the requested 9/7/2 (or user-overridden) structure:
  - If the slot is already filled with a real entered song, emit it with
    state="entered".
  - Otherwise, score candidates from the live state (played songs so far
    PLUS any previously-previewed top-1 picks for earlier unfilled slots).
    Emit top_k alternatives.
"""

import sqlite3
from phishpicker.live import get_live_show
from phishpicker.predict import predict_next


def build_preview(
    read: sqlite3.Connection,
    live: sqlite3.Connection,
    show_id: str,
    *,
    set1: int,
    set2: int,
    encore: int,
    top_k: int,
    scorer,
) -> dict:
    show = get_live_show(live, show_id)
    if show is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="show not found")

    entered_by_set_pos: dict[tuple[str, int], dict] = {}
    # get_live_show returns songs in enter order; we need position-per-set.
    per_set_positions: dict[str, int] = {}
    for s in show["songs"]:
        per_set_positions[s["set_number"]] = per_set_positions.get(s["set_number"], 0) + 1
        entered_by_set_pos[(s["set_number"], per_set_positions[s["set_number"]])] = s

    structure = [("1", set1), ("2", set2), ("E", encore)]
    slots = []
    slot_idx = 0
    for set_number, n in structure:
        for pos in range(1, n + 1):
            slot_idx += 1
            entered = entered_by_set_pos.get((set_number, pos))
            if entered:
                slots.append({
                    "slot_idx": slot_idx,
                    "set_number": set_number,
                    "position": pos,
                    "state": "entered",
                    "entered_song": entered,
                })
            else:
                # use predict_next against the current live state; pick top-1
                # and roll it forward for downstream slots by appending to a
                # scratch play-list. NOTE: we do NOT modify the real live DB;
                # we rebuild a virtual played list.
                cands = predict_next(read, live, show_id, top_n=top_k, scorer=scorer)
                slots.append({
                    "slot_idx": slot_idx,
                    "set_number": set_number,
                    "position": pos,
                    "state": "predicted",
                    "top_k": cands,
                })
                # TODO: roll top-1 into scratch state for next iteration
    return {"slots": slots}
```

**Critical caveat:** `predict_next` reads from the `live` DB. Rolling
forward requires a scratch mechanism — either:
(a) extending `predict_next` to accept an in-memory "virtual played" list, or
(b) cloning the live DB to `:memory:`, mutating, predicting against the clone.

(a) is cleaner. Look at `predict.py` to see how `played_songs` is computed;
add an optional param to pass them directly. If that's invasive, fall back
to (b) — copy live rows into an ephemeral in-memory sqlite, append virtual
entries there, predict against that.

**Step 3: Run tests — pass**

**Step 4: Commit**
```bash
git commit -am "feat(api): /live/show/{id}/preview — autoregressive full-show preview"
```

---

### Task 5: `/live/show/{show_id}/slot/{idx}/alternatives`

Given the live state + a slot index, return top-10 alternatives specifically
for that slot (may be redundant with `/preview` but cheaper for the modal
flow).

**Step 1: Failing test**

```python
def test_slot_alternatives_returns_top_k_for_predicted_slot(api_client, live_show):
    r = api_client.get(f"/live/show/{live_show['show_id']}/slot/5/alternatives?top_k=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["candidates"]) == 5
    assert body["candidates"][0]["rank"] == 1


def test_slot_alternatives_404s_for_entered_slot(api_client, live_show_with_song):
    # slot 1 is entered; hitting alternatives for it returns the entered
    # song plus a note rather than fresh predictions (OR 409 — bikeshed).
    r = api_client.get(f"/live/show/{live_show_with_song['show_id']}/slot/1/alternatives")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "entered"
```

**Step 2: Implement** — reuses `build_preview` and returns the slot's entry:

```python
@app.get("/live/show/{show_id}/slot/{slot_idx}/alternatives")
def slot_alternatives(
    show_id: str, slot_idx: int, request: Request,
    set1: int = 9, set2: int = 7, encore: int = 2, top_k: int = 10,
    read: sqlite3.Connection = Depends(get_read),
    live: sqlite3.Connection = Depends(get_live),
):
    preview = build_preview(read, live, show_id, set1=set1, set2=set2,
                             encore=encore, top_k=top_k,
                             scorer=request.app.state.scorer)
    if slot_idx < 1 or slot_idx > len(preview["slots"]):
        raise HTTPException(404)
    return preview["slots"][slot_idx - 1]
```

**Step 3: Commit**
```bash
git commit -am "feat(api): /live/show/{id}/slot/{idx}/alternatives"
```

---

### Task 6: `/songs` bustout POST

**Step 1: Failing test**

```python
def test_post_songs_inserts_bustout_placeholder(api_client, populated_db):
    r = api_client.post("/songs", json={"name": "Mystery Song"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Mystery Song"
    assert body["is_bustout_placeholder"] is True
    assert isinstance(body["song_id"], int)
    # second insert of same name returns existing row (idempotent)
    r2 = api_client.post("/songs", json={"name": "Mystery Song"})
    assert r2.status_code == 200
    assert r2.json()["song_id"] == body["song_id"]
```

**Step 2: Implement**

```python
from datetime import UTC, datetime
from fastapi import status
from pydantic import BaseModel

class NewSong(BaseModel):
    name: str

@app.post("/songs", status_code=201)
def insert_song(body: NewSong, response: Response,
                conn: sqlite3.Connection = Depends(get_read_write_songs)):
    existing = conn.execute(
        "SELECT song_id, name, is_bustout_placeholder FROM songs WHERE name = ?",
        (body.name,),
    ).fetchone()
    if existing:
        response.status_code = 200
        return dict(existing)
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "INSERT INTO songs (name, first_seen_at, is_bustout_placeholder) VALUES (?, ?, 1)",
        (body.name, now),
    )
    conn.commit()
    song_id = cur.lastrowid
    return {"song_id": song_id, "name": body.name, "is_bustout_placeholder": True}
```

You'll need a `get_read_write_songs` connection factory (the existing
`get_read` is read-only). Add it to `app.py`.

**Step 3: Commit**
```bash
git commit -am "feat(api): POST /songs — insert bustout placeholder"
```

---

## Phase 2 — phish.net live sync

### Task 7: `live_sync.py` module — reconcile logic, no I/O

Pure function over lists that does the reconcile math. Testable in isolation.

**Files:**
- Create: `api/src/phishpicker/live_sync.py`
- Create: `api/tests/test_live_sync.py`

**Step 1: Failing test**

```python
# api/tests/test_live_sync.py
from phishpicker.live_sync import reconcile, ReconcileAction


def _sent(song_id, set_num="1"): return {"song_id": song_id, "set_number": set_num}


def test_reconcile_appends_when_phishnet_ahead():
    user = [_sent(1), _sent(2)]
    net = [_sent(1), _sent(2), _sent(3), _sent(4)]
    actions = reconcile(user, net)
    assert [a.kind for a in actions] == ["append", "append"]
    assert actions[0].song_id == 3


def test_reconcile_noop_when_aligned():
    user = net = [_sent(1), _sent(2), _sent(3)]
    assert reconcile(user, net) == []


def test_reconcile_noop_when_user_ahead():
    user = [_sent(1), _sent(2), _sent(3)]
    net = [_sent(1), _sent(2)]
    assert reconcile(user, net) == []


def test_reconcile_override_on_mismatch():
    user = [_sent(1), _sent(2), _sent(99)]
    net = [_sent(1), _sent(2), _sent(3)]
    actions = reconcile(user, net)
    assert len(actions) == 1
    assert actions[0].kind == "override"
    assert actions[0].slot_idx == 3
    assert actions[0].old_song_id == 99
    assert actions[0].song_id == 3


def test_reconcile_bustout_flags_unknown_song(monkeypatch):
    user = [_sent(1)]
    net = [_sent(1), {"song_id": 777, "set_number": "1", "is_unknown": True}]
    actions = reconcile(user, net)
    assert actions[0].kind == "append"
    assert actions[0].is_bustout is True
```

**Step 2: Implement**

```python
# api/src/phishpicker/live_sync.py
"""Pure reconciliation between user-entered songs and phish.net's feed."""
from dataclasses import dataclass


@dataclass
class ReconcileAction:
    kind: str       # "append" | "override"
    slot_idx: int   # 1-indexed
    song_id: int
    set_number: str
    old_song_id: int | None = None
    is_bustout: bool = False


def reconcile(user_rows: list[dict], net_rows: list[dict]) -> list[ReconcileAction]:
    actions: list[ReconcileAction] = []
    for i in range(max(len(user_rows), len(net_rows))):
        has_user = i < len(user_rows)
        has_net = i < len(net_rows)
        if not has_net:
            break  # user is ahead; nothing to reconcile
        net = net_rows[i]
        if not has_user:
            actions.append(ReconcileAction(
                kind="append", slot_idx=i + 1,
                song_id=net["song_id"], set_number=net["set_number"],
                is_bustout=bool(net.get("is_unknown")),
            ))
            continue
        user = user_rows[i]
        if user["song_id"] == net["song_id"]:
            continue
        actions.append(ReconcileAction(
            kind="override", slot_idx=i + 1,
            song_id=net["song_id"], set_number=net["set_number"],
            old_song_id=user["song_id"],
            is_bustout=bool(net.get("is_unknown")),
        ))
    return actions
```

**Step 3: Commit**
```bash
git commit -am "feat(live-sync): reconcile — pure user-vs-phishnet diff logic"
```

---

### Task 8: `sync_show_with_phishnet` I/O function

Wires `reconcile` to phish.net + the live DB + songs DB. Still testable
via `pytest-httpx`.

**Step 1: Failing test**

```python
def test_sync_show_appends_when_phishnet_adds_songs(httpx_mock, live_setup):
    # live_setup: fresh live show with 1 song entered; phish.net returns 3.
    from phishpicker.live_sync import sync_show_with_phishnet
    httpx_mock.add_response(..., json={"data": [
        {"songid": 1, "song": "A", "set": "1", "position": 1},
        {"songid": 2, "song": "B", "set": "1", "position": 2},
        {"songid": 3, "song": "C", "set": "1", "position": 3},
    ]})
    result = sync_show_with_phishnet(
        read_conn=live_setup.read, live_conn=live_setup.live,
        phishnet_client=live_setup.client,
        show_id=live_setup.show_id, show_date="2026-04-23",
    )
    assert result["appended"] == 2
    assert result["overrides"] == 0
    assert result["bustouts"] == 0
```

**Step 2: Implement**

```python
def sync_show_with_phishnet(*, read_conn, live_conn, phishnet_client,
                            show_id: str, show_date: str) -> dict:
    from phishpicker.live import get_live_show, append_song, delete_last_song
    # Fetch phish.net's current view.
    raw = phishnet_client._get(f"setlists/showdate/{show_date}.json", {})
    net_rows_raw = [r for r in raw if r.get("artist_name") == "Phish"]
    net_rows_raw.sort(key=lambda r: (_SET_ORDER.get(str(r["set"]).upper(), 99), int(r["position"])))

    # Resolve phish.net song_ids against local songs table; detect bustouts.
    net_rows: list[dict] = []
    for r in net_rows_raw:
        sid = _resolve_song_id(read_conn, int(r["songid"]), r.get("song", ""))
        net_rows.append({
            "song_id": sid["song_id"],
            "set_number": str(r["set"]).upper(),
            "is_unknown": sid["is_unknown"],
        })

    live_show = get_live_show(live_conn, show_id)
    user_rows = [
        {"song_id": s["song_id"], "set_number": s["set_number"]}
        for s in live_show["songs"]
    ]
    actions = reconcile(user_rows, net_rows)

    appended = overrides = bustouts = 0
    for a in actions:
        if a.kind == "override":
            delete_last_song(live_conn, show_id)  # simplistic; see note below
            append_song(live_conn, show_id, a.song_id, a.set_number)
            overrides += 1
        else:
            append_song(live_conn, show_id, a.song_id, a.set_number)
            appended += 1
        if a.is_bustout:
            bustouts += 1
    return {"appended": appended, "overrides": overrides, "bustouts": bustouts}
```

Note: the override path uses `delete_last_song` which only deletes the
very last row, so it only works when the override is at the tail. For
interior-slot overrides you'd need a `replace_song_at(entered_order, …)`
function. For the Sphere residency, phish.net-vs-user overrides at a
specific slot are rare; append-case dominates. Punt on interior overrides
— just log a warning and skip.

**Step 3: Commit**
```bash
git commit -am "feat(live-sync): sync_show_with_phishnet — end-to-end reconciliation"
```

---

### Task 9: Background poller task

**Files:**
- Modify: `api/src/phishpicker/app.py` — register a poller lifespan task
- Create: `api/tests/test_poller.py`

**Step 1: Failing test**

```python
import asyncio

async def test_poller_runs_sync_on_interval(mocker):
    from phishpicker.live_sync import start_poller, stop_poller
    calls = []
    async def fake_sync(*, show_id, **kw):
        calls.append(show_id)
    mocker.patch("phishpicker.live_sync._run_sync_once", fake_sync)
    await start_poller(show_id="abc", show_date="2026-04-23", interval=0.05)
    await asyncio.sleep(0.12)
    await stop_poller("abc")
    assert len(calls) >= 2
```

**Step 2: Implement with asyncio.create_task**

```python
# live_sync.py additions
import asyncio
from typing import Callable

_POLLERS: dict[str, asyncio.Task] = {}


async def start_poller(show_id: str, show_date: str, interval: float = 60.0,
                       sync_fn: Callable = None):
    """Start a background poller for show_id. Idempotent — no-op if running."""
    if show_id in _POLLERS and not _POLLERS[show_id].done():
        return
    _POLLERS[show_id] = asyncio.create_task(
        _poll_loop(show_id, show_date, interval, sync_fn or _run_sync_once)
    )


async def stop_poller(show_id: str):
    task = _POLLERS.pop(show_id, None)
    if task and not task.done():
        task.cancel()


async def _poll_loop(show_id, show_date, interval, sync_fn):
    while True:
        try:
            await sync_fn(show_id=show_id, show_date=show_date)
        except Exception as e:
            # log; keep running
            import logging
            logging.getLogger(__name__).warning("sync failed for %s: %s", show_id, e)
        await asyncio.sleep(interval)


async def _run_sync_once(*, show_id: str, show_date: str):
    # Thin async wrapper around the sync `sync_show_with_phishnet`.
    # Uses the app's singleton client + per-call DB connections.
    from phishpicker.app import _get_app  # or plumb state via closure
    app = _get_app()
    ...
```

The async/sync bridge is awkward because FastAPI is async but our DB +
PhishNetClient are sync. Use `asyncio.to_thread(sync_show_with_phishnet, ...)`.

**Step 3: Wire start/stop to endpoints**

```python
@app.post("/live/show/{show_id}/sync/start")
async def sync_start(show_id: str, body: dict):
    from phishpicker.live_sync import start_poller
    await start_poller(show_id, body["show_date"], interval=60.0)
    return {"started": True}


@app.post("/live/show/{show_id}/sync/stop")
async def sync_stop(show_id: str):
    from phishpicker.live_sync import stop_poller
    await stop_poller(show_id)
    return {"stopped": True}
```

**Step 4: Sync status query**

```python
@app.get("/live/show/{show_id}/sync/status")
async def sync_status(show_id: str):
    from phishpicker.live_sync import poller_status
    return poller_status(show_id)  # {"state": "live"|"stale"|"dead"|"off", "last_updated": ..., "last_error": ...}
```

Requires tracking `last_updated` and `last_error` per poller — add to
`_POLLERS` dict as a richer struct.

**Step 5: Commit**
```bash
git commit -am "feat(api): live sync background poller + start/stop/status endpoints"
```

---

## Phase 3 — Frontend

### Task 10: Auto-load next show + header

**Files:**
- Modify: `web/src/app/page.tsx` — replace the "Start show" button with
  auto-upcoming-load flow.
- Create: `web/src/components/ShowHeader.tsx` + test.

**⚠ Next.js 16 check:** Read `web/node_modules/next/dist/docs/` entries
for client components and fetch patterns. `"use client"` still exists but
the data-fetching story may have shifted. The transparent `/api/[...path]`
proxy already works, so SWR is the simplest path.

**Step 1: Failing frontend test**

```tsx
// web/src/components/ShowHeader.test.tsx
import { render } from "@testing-library/react";
import { ShowHeader } from "./ShowHeader";

test("renders date venue city", () => {
  const { getByText } = render(
    <ShowHeader show={{
      show_date: "2026-04-23", venue: "Sphere",
      city: "Las Vegas", state: "NV", show_id: 1,
    }} />,
  );
  expect(getByText("2026-04-23")).toBeInTheDocument();
  expect(getByText(/Sphere/)).toBeInTheDocument();
  expect(getByText(/Las Vegas, NV/)).toBeInTheDocument();
});
```

**Step 2: Implement** — plain component, no state.

```tsx
export interface UpcomingShow {
  show_id: number;
  show_date: string;
  venue: string;
  city: string;
  state: string;
}

export function ShowHeader({ show }: { show: UpcomingShow }) {
  return (
    <div className="px-4 pt-6 pb-2">
      <div className="text-2xl font-bold tracking-tight">{show.show_date}</div>
      <div className="text-sm text-neutral-400">
        {show.venue} · {show.city}, {show.state}
      </div>
    </div>
  );
}
```

**Step 3: Wire into `page.tsx`** — use SWR to fetch `/api/upcoming`; when
show changes from null to a value, call `startShow(show.show_date, ...)`
automatically.

**Step 4: Commit**
```bash
git commit -am "feat(web): ShowHeader + auto-load next Phish show"
```

---

### Task 11: Full grayed preview component

**Files:**
- Create: `web/src/components/FullPreview.tsx` + test.
- Create: `web/src/lib/preview.ts` (SWR hook for `/live/show/:id/preview`).

**Step 1: Failing test**

```tsx
test("renders all slots with set dividers", () => {
  const preview = {
    slots: [
      ...[1,2,3,4,5,6,7,8,9].map(i => ({slot_idx: i, set_number: "1", position: i, state: "predicted", top_k: [{song_id: i, name: `song${i}`, score: 1, rank: 1}]})),
      ...[10,11,12,13,14,15,16].map(i => ({slot_idx: i, set_number: "2", position: i-9, state: "predicted", top_k: [{song_id: i, name: `song${i}`, score: 1, rank: 1}]})),
      ...[17,18].map(i => ({slot_idx: i, set_number: "E", position: i-16, state: "predicted", top_k: [{song_id: i, name: `song${i}`, score: 1, rank: 1}]})),
    ],
  };
  const { getAllByRole, getByText } = render(<FullPreview preview={preview} onSlotClick={() => {}} />);
  expect(getByText("SET 1")).toBeInTheDocument();
  expect(getByText("SET 2")).toBeInTheDocument();
  expect(getByText("ENCORE")).toBeInTheDocument();
  // 18 slot rows
  expect(getAllByRole("button").filter(b => b.dataset.slot).length).toBe(18);
});
```

**Step 2: Implement** — list rendering with set dividers, gray text, on-click
passes slot_idx upward.

**Step 3: Commit**
```bash
git commit -am "feat(web): FullPreview — grayed-out full setlist preview"
```

---

### Task 12: Slot-alts modal

**Files:**
- Create: `web/src/components/SlotAltsModal.tsx` + test.

Renders top-10 alts for a given slot (reuses `Leaderboard` internals).
Client hits `/api/live/show/:id/slot/:idx/alternatives`.

**Step 1-5:** Test + implement + commit. Mobile bottom-sheet style.

**Commit:** `feat(web): SlotAltsModal — top-10 alts for grayed slots`

---

### Task 13: Sync status pill + toggle

**Files:**
- Create: `web/src/components/SyncStatus.tsx` + test.
- Modify: `web/src/lib/liveShow.ts` — add `sync` state + `toggleSync()`.

**Step 1-5:** Poll `/api/live/show/:id/sync/status` every 5s (SWR). Pill
renders `live` / `stale` / `dead` / `off` with colored dot. Tap to toggle
via POST `/sync/start|stop`.

**Commit:** `feat(web): SyncStatus pill + toggle wiring`

---

### Task 14: Bustout add flow in SongSearch

**Files:**
- Modify: `web/src/components/SongSearch.tsx` — when 0 matches, offer
  "Add '$query' as new song?"
- Modify: `web/src/components/SongSearch.test.tsx`.

**Step 1-5:** Test the UI + test that tapping the add button hits
`POST /api/songs` and then calls `onAdd` with the returned song.

**Commit:** `feat(web): SongSearch — add bustout flow for unmatched query`

---

### Task 15: Integrate all new pieces in `page.tsx`

**Files:**
- Modify: `web/src/app/page.tsx`.

Compose: `ShowHeader` → `FullPreview` (primary view) → sticky footer with
typeahead + undo + set-transition. `SlotAltsModal` opens on slot click.
`SyncStatus` pill in header.

The existing `Leaderboard` can go — `FullPreview` shows next-slot top-1
inline. Or keep `Leaderboard` as a compact "next song" view above the full
preview. User preference; default is to drop it.

Page tests can assert rough composition.

**Commit:** `feat(web): integrate header/preview/sync in main page`

---

## Phase 4 — Deploy + verify

### Task 16: Local integration run

```bash
cd api && uv run uvicorn phishpicker.app:create_app --factory --reload &
cd web && npm run dev &
```

Visit `http://localhost:3000`. Expected:
- Header shows next upcoming Phish show
- Full preview renders 9/7/2
- Sync pill is "off" until toggled on
- Typing a song name + enter appends it + predictions recompute

Commit any bugs found.

### Task 17: Deploy to NAS

Use existing `scripts/deploy_to_nas.sh` or equivalent:
- Build web Docker image
- Push both api + web
- Verify Cloudflare tunnel routes

Confirm from phone on LTE that live page loads + sync works.

**Commit:** docs-only, or RESUME update describing deployed state.

---

## Phase 5 — Nice-to-haves (post-Night-7)

Defer until after 2026-04-30:
- Reconciliation view (diff user session vs. phish.net final)
- Retro integration (feed reconciled setlist to retro harness)
- "Why this song?" explainability
- Desktop-optimized layout

---

## Summary

**16 tasks across 4 phases.** Phase 1-2 (backend) is ~6 hours. Phase 3
(frontend) is ~8 hours pending Next.js 16 doc-reading. Phase 4 is 1-2h
pending NAS SSH window. Total: ~15-16 hours to "Night 7 ready."

**Deployment dry-run before Thursday 4/23**: at minimum Phase 1 + Phase 2
+ Phase 3 Tasks 10-13 (auto-load + preview + sync) need to ship. That's
roughly 12 hours of work — doable by Thursday if we start now.
