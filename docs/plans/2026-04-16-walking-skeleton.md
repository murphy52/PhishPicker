# Phishpicker Walking Skeleton Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a thin end-to-end vertical slice — phish.net ingest → SQLite → heuristic song predictor → FastAPI → Next.js UI → deployed to NAS — so every layer of the architecture is exercised before we commit to the LightGBM model work.

**Architecture:** Two Docker containers (`api`: FastAPI + Python, `web`: Next.js) in one compose stack on the NAS. Training/ingestion runs on the Mac mini and ships a SQLite snapshot + (eventually) model artifacts via `scp` + atomic rename to a shared NAS volume. Cloudflare tunnel + Authentik in front of the `web` container only. For this skeleton the "model" is a hand-tuned heuristic (Approach 1 from the design doc) — no ML yet. Real LightGBM lands in a later plan.

**Tech Stack:** Python 3.12, uv, FastAPI, httpx, pytest, SQLite. Next.js 15 App Router, TypeScript, Tailwind, Vitest, Fuse.js for type-ahead. Docker + docker-compose. Ruff, prettier, pre-commit.

**Supporting docs:** `docs/plans/2026-04-16-phishpicker-design.md` (the full design — read first).

**Scope (what's IN this plan):**
- Project scaffolding (both backend + frontend)
- phish.net API client with recorded fixtures
- SQLite schema + ingestion with idempotency
- Derived fields (run position, tour position)
- Heuristic scorer (frequency × recency × venue/run/tour context) + hard rules
- API: `/meta`, `/songs`, `/predict/{show_id}`, live-show CRUD
- UI: single live-show page — leaderboard, played strip, add-song sheet, set-boundary button, undo
- Docker-compose stack + Dockerfiles
- Mac mini ingestion script + deploy script
- Docs for one-time Cloudflare + Authentik setup

**Scope (what's OUT, deferred to later plans):**
- Any ML / LightGBM
- Walk-forward evaluation harness
- Bust-out watch, song detail pages, show archive, replay mode
- Jam-length model
- Feature determinism / training-serving skew tests (no ML yet)
- Websocket realtime

---

## Conventions for this plan

- **Commit format**: per the user's global CLAUDE.md, every commit message ends with a blank line then `🤖 assist`. Use that sign-off (not `Co-Authored-By`).
- **TDD**: test first, watch it fail, implement minimal, watch it pass, commit.
- **Backend code** lives in `api/` (Python project root, editable install with `uv`).
- **Frontend code** lives in `web/` (Next.js project root).
- **Shared data directory on NAS** is `/volume/phishpicker/data/` — mounted into both containers read-only (`api` reads, Mac mini writes via scp).
- **Dev data directory locally** is `./data/` (gitignored).
- **Python package name**: `phishpicker`.
- **Run tests**: `uv run pytest -v` (from `api/`), `npm test` (from `web/`).
- **Format**: `uv run ruff format .` + `uv run ruff check .` (backend), `npm run format` (frontend).

---

## Task 0: Repo hygiene (handle API key, gitignore, README skeleton)

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `.env.example`
- Remove: `phishnet-api-key.txt` (move contents to `.env` — local, gitignored)

**Step 1: Write `.gitignore`**

```
# data
data/
*.db
*.db-journal
*.db-wal
*.db-shm
*.pkl
*.joblib
# secrets
.env
.env.local
phishnet-api-key.txt
# python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
# node
node_modules/
.next/
dist/
# editors
.DS_Store
.vscode/
.idea/
```

**Step 2: Move the API key out of the repo root**

```bash
# Create local .env with the existing key
echo "PHISHNET_API_KEY=$(cat phishnet-api-key.txt)" > .env
# Remove the loose key file
rm phishnet-api-key.txt
```

**Step 3: Create `.env.example`**

```
PHISHNET_API_KEY=your_key_here
```

**Step 4: Create `README.md` (skeleton — one paragraph)**

```markdown
# Phishpicker

Predicts Phish's next song from setlist history. See
[the design doc](docs/plans/2026-04-16-phishpicker-design.md) for the full
design and [the walking-skeleton plan](docs/plans/2026-04-16-walking-skeleton.md)
for the current implementation phase.
```

**Step 5: Commit**

```bash
git add .gitignore README.md .env.example
git commit -m "chore: add gitignore, env example, and readme; remove loose api key

🤖 assist"
```

---

## Task 1: Python project scaffolding

**Files:**
- Create: `api/pyproject.toml`
- Create: `api/src/phishpicker/__init__.py`
- Create: `api/src/phishpicker/config.py`
- Create: `api/tests/__init__.py`
- Create: `api/tests/conftest.py`
- Create: `api/.python-version`
- Create: `api/ruff.toml`

**Step 1: Ensure `uv` is installed**

```bash
which uv || curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Step 2: Create `api/pyproject.toml`**

```toml
[project]
name = "phishpicker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi[standard]>=0.115",
    "httpx>=0.27",
    "pydantic>=2.9",
    "python-dotenv>=1.0",
    "uvicorn[standard]>=0.32",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.32",
    "ruff>=0.7",
]

[project.scripts]
phishpicker = "phishpicker.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]

[tool.hatch.build.targets.wheel]
packages = ["src/phishpicker"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 3: Create `api/.python-version`**

```
3.12
```

**Step 4: Create `api/ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM"]
ignore = ["E501"]

[format]
quote-style = "double"
```

**Step 5: Create `api/src/phishpicker/__init__.py`**

```python
__version__ = "0.1.0"
```

**Step 6: Create `api/src/phishpicker/config.py`**

```python
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment."""

    phishnet_api_key: str = Field(..., alias="PHISHNET_API_KEY")
    data_dir: Path = Field(default=Path("./data"), alias="PHISHPICKER_DATA_DIR")
    phishnet_base_url: str = "https://api.phish.net/v5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "phishpicker.db"

    @property
    def live_db_path(self) -> Path:
        return self.data_dir / "live.db"
```

Note: add `pydantic-settings>=2.6` to `[project]` dependencies when you run step 8.

**Step 7: Create `api/tests/conftest.py`**

```python
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

**Step 8: Install, verify**

```bash
cd api
# add pydantic-settings to pyproject.toml dependencies first
uv sync --all-extras
uv run python -c "import phishpicker; print(phishpicker.__version__)"
```

Expected: `0.1.0`

**Step 9: Commit**

```bash
cd ..
git add api/
git commit -m "chore: scaffold python backend project

🤖 assist"
```

---

## Task 2: Next.js project scaffolding

**Files:**
- Create: `web/` (via `create-next-app`)
- Modify: `web/tailwind.config.ts` (enable dark-mode class)
- Create: `web/src/lib/api.ts`
- Create: `web/.env.example`
- Create: `web/.env.local` (gitignored)

**Step 1: Scaffold via create-next-app**

```bash
npx create-next-app@latest web \
  --typescript \
  --tailwind \
  --app \
  --src-dir \
  --eslint \
  --import-alias "@/*" \
  --no-turbopack
```

**Step 2: Install runtime deps**

```bash
cd web
npm install fuse.js swr
npm install --save-dev vitest @vitejs/plugin-react @testing-library/react @testing-library/jest-dom jsdom
```

**Step 3: Configure Vitest**

Create `web/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
});
```

Create `web/vitest.setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

Add to `web/package.json` scripts:
```json
"test": "vitest run",
"test:watch": "vitest"
```

**Step 4: Create `web/src/lib/api.ts`** (server-side proxy helper)

```ts
const API_BASE = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}
```

**Step 5: Create `web/.env.example`**

```
API_INTERNAL_URL=http://api:8000
```

**Step 6: Configure dark-mode default**

Edit `web/src/app/layout.tsx` — add `className="dark bg-neutral-950 text-neutral-100"` to `<html>`.

**Step 7: Smoke test**

```bash
cd web && npm run build
```

Expected: successful build, no errors.

**Step 8: Commit**

```bash
cd ..
git add web/
git commit -m "chore: scaffold next.js frontend project

🤖 assist"
```

---

## Task 3: Database schema (SQLite, plain SQL)

**Files:**
- Create: `api/src/phishpicker/db/__init__.py`
- Create: `api/src/phishpicker/db/schema.sql`
- Create: `api/src/phishpicker/db/connection.py`
- Create: `api/tests/db/test_connection.py`

**Step 1: Write the failing test**

`api/tests/db/test_connection.py`:
```python
from pathlib import Path

import pytest

from phishpicker.db.connection import open_db, apply_schema


def test_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert {"songs", "venues", "tours", "shows", "setlist_songs", "schema_meta"} <= tables


def test_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = open_db(db_path)
    apply_schema(conn)
    apply_schema(conn)  # second apply must not raise
    conn.close()
```

**Step 2: Run — expect import failure**

```bash
cd api && uv run pytest tests/db/test_connection.py -v
```

Expected: FAIL with `ImportError` or `ModuleNotFoundError`.

**Step 3: Write `schema.sql`**

`api/src/phishpicker/db/schema.sql`:
```sql
-- Schema version tracker
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');

CREATE TABLE IF NOT EXISTS songs (
    song_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    original_artist TEXT,
    debut_date TEXT,
    first_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_songs_name ON songs(name);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    state TEXT,
    country TEXT
);

CREATE TABLE IF NOT EXISTS tours (
    tour_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT
);

CREATE TABLE IF NOT EXISTS shows (
    show_id INTEGER PRIMARY KEY,
    show_date TEXT NOT NULL,                  -- ISO YYYY-MM-DD
    venue_id INTEGER REFERENCES venues(venue_id),
    tour_id INTEGER REFERENCES tours(tour_id),
    run_position INTEGER,                     -- nth show of a same-venue consecutive run
    run_length INTEGER,                       -- total shows in that run
    tour_position INTEGER,                    -- nth show in tour
    fetched_at TEXT NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_shows_date ON shows(show_date);
CREATE INDEX IF NOT EXISTS idx_shows_venue ON shows(venue_id);

CREATE TABLE IF NOT EXISTS setlist_songs (
    show_id INTEGER NOT NULL REFERENCES shows(show_id),
    set_number TEXT NOT NULL,                 -- '1','2','3','E'
    position INTEGER NOT NULL,
    song_id INTEGER NOT NULL REFERENCES songs(song_id),
    trans_mark TEXT NOT NULL DEFAULT ',',     -- ',', '>', '->'
    PRIMARY KEY (show_id, set_number, position)
);
CREATE INDEX IF NOT EXISTS idx_setlist_song ON setlist_songs(song_id);
CREATE INDEX IF NOT EXISTS idx_setlist_show ON setlist_songs(show_id);
```

**Step 4: Write `connection.py`**

`api/src/phishpicker/db/connection.py`:
```python
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def open_db(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)
    conn.commit()
```

Create `api/src/phishpicker/db/__init__.py`:
```python
from phishpicker.db.connection import apply_schema, open_db

__all__ = ["apply_schema", "open_db"]
```

Create `api/tests/db/__init__.py` (empty).

**Step 5: Run — expect pass**

```bash
uv run pytest tests/db/test_connection.py -v
```

Expected: 2 passed.

**Step 6: Commit**

```bash
cd ..
git add api/
git commit -m "feat: sqlite schema for shows, songs, venues, setlists

🤖 assist"
```

---

## Task 4: Live-show DB schema

**Files:**
- Create: `api/src/phishpicker/db/live_schema.sql`
- Modify: `api/src/phishpicker/db/connection.py` (add `apply_live_schema`)
- Create: `api/tests/db/test_live_schema.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from phishpicker.db.connection import apply_live_schema, open_db


def test_live_schema_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    conn = open_db(db_path)
    apply_live_schema(conn)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert {"live_show", "live_songs"} <= tables
```

**Step 2: Run — expect fail**

**Step 3: Create `live_schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS live_show (
    show_id TEXT PRIMARY KEY,          -- client-generated uuid
    show_date TEXT NOT NULL,
    venue_id INTEGER,
    started_at TEXT NOT NULL,
    current_set TEXT NOT NULL DEFAULT '1',   -- '1','2','3','E'
    reconciled_at TEXT
);

CREATE TABLE IF NOT EXISTS live_songs (
    show_id TEXT NOT NULL REFERENCES live_show(show_id) ON DELETE CASCADE,
    entered_order INTEGER NOT NULL,
    song_id INTEGER NOT NULL,
    set_number TEXT NOT NULL,
    trans_mark TEXT NOT NULL DEFAULT ',',
    entered_at TEXT NOT NULL,
    PRIMARY KEY (show_id, entered_order)
);
```

**Step 4: Add `apply_live_schema` to `connection.py`**

```python
LIVE_SCHEMA_PATH = Path(__file__).parent / "live_schema.sql"


def apply_live_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(LIVE_SCHEMA_PATH.read_text())
    conn.commit()
```

Export it from `__init__.py`.

**Step 5: Run — expect pass**

**Step 6: Commit**

```bash
git add api/
git commit -m "feat: live-show sqlite schema

🤖 assist"
```

---

## Task 5: phish.net API client + fixtures

**Files:**
- Create: `api/src/phishpicker/phishnet/__init__.py`
- Create: `api/src/phishpicker/phishnet/client.py`
- Create: `api/tests/phishnet/test_client.py`
- Create: `api/tests/fixtures/phishnet_songs_sample.json` (small hand-curated sample)
- Create: `api/tests/fixtures/phishnet_shows_sample.json`
- Create: `api/tests/fixtures/phishnet_setlist_show1234567.json`

**Context note:** phish.net v5 exact schema must be verified while implementing. The client should be a thin typed wrapper that returns raw JSON; feature extraction happens downstream. Keep the contract surface tiny.

**Step 1: Hand-craft the fixtures**

Small but real-shape examples. Two songs, one venue, one show with a 3-song setlist. Examples below — verify exact field names against phish.net's live API once you have the key loaded.

`phishnet_songs_sample.json`:
```json
{
  "error": false,
  "data": [
    {"songid": 100, "song": "Chalk Dust Torture", "artist": "Phish", "debut": "1991-10-04"},
    {"songid": 101, "song": "Tweezer", "artist": "Phish", "debut": "1990-08-17"}
  ]
}
```

`phishnet_shows_sample.json`:
```json
{
  "error": false,
  "data": [
    {"showid": 1234567, "showdate": "2024-07-21", "venueid": 500, "tourid": 77,
     "venue": "Madison Square Garden", "city": "New York", "state": "NY", "country": "USA"}
  ]
}
```

`phishnet_setlist_show1234567.json`:
```json
{
  "error": false,
  "data": [
    {"showid": 1234567, "showdate": "2024-07-21", "set": "1", "position": 1,
     "songid": 100, "song": "Chalk Dust Torture", "trans_mark": ","},
    {"showid": 1234567, "showdate": "2024-07-21", "set": "1", "position": 2,
     "songid": 101, "song": "Tweezer", "trans_mark": ">"}
  ]
}
```

**Step 2: Write the failing tests**

`api/tests/phishnet/test_client.py`:
```python
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from phishpicker.phishnet.client import PhishNetClient


@pytest.fixture
def client() -> PhishNetClient:
    return PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5")


def test_fetch_shows_since(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_shows_sample.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/shows.json?apikey=test-key&order_by=showdate&direction=desc",
        text=body,
    )
    shows = client.fetch_shows_since("1900-01-01")
    assert len(shows) == 1
    assert shows[0]["showid"] == 1234567


def test_fetch_setlist(client: PhishNetClient, httpx_mock: HTTPXMock, fixtures_dir: Path):
    body = (fixtures_dir / "phishnet_setlist_show1234567.json").read_text()
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/get.json?apikey=test-key&showid=1234567",
        text=body,
    )
    setlist = client.fetch_setlist(1234567)
    assert len(setlist) == 2
    assert setlist[1]["trans_mark"] == ">"
```

(Adjust URL patterns to match phish.net v5's actual endpoints once verified.)

**Step 3: Run — expect fail**

**Step 4: Implement `PhishNetClient`**

`api/src/phishpicker/phishnet/client.py`:
```python
import httpx


class PhishNetError(Exception):
    pass


class PhishNetClient:
    def __init__(self, api_key: str, base_url: str = "https://api.phish.net/v5", timeout: float = 30.0):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def _get(self, path: str, params: dict) -> list[dict]:
        params = {**params, "apikey": self._api_key}
        r = self._client.get(f"{self._base_url}/{path}", params=params)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise PhishNetError(body.get("error_message") or "phish.net error")
        return body.get("data", [])

    def fetch_shows_since(self, show_date: str) -> list[dict]:
        """All shows (caller filters by date). v5's filter syntax varies; start permissive."""
        return self._get("shows.json", {"order_by": "showdate", "direction": "desc"})

    def fetch_setlist(self, show_id: int) -> list[dict]:
        return self._get("setlists/get.json", {"showid": show_id})

    def fetch_songs(self) -> list[dict]:
        return self._get("songs.json", {})

    def fetch_venues(self) -> list[dict]:
        return self._get("venues.json", {})

    def close(self) -> None:
        self._client.close()
```

**Step 5: Run — expect pass**

```bash
uv run pytest tests/phishnet/ -v
```

**Step 6: Commit**

```bash
git add api/
git commit -m "feat: phish.net v5 api client with fixture-based tests

🤖 assist"
```

---

## Task 6: Ingestion — songs and venues

**Files:**
- Create: `api/src/phishpicker/ingest/__init__.py`
- Create: `api/src/phishpicker/ingest/songs.py`
- Create: `api/src/phishpicker/ingest/venues.py`
- Create: `api/tests/ingest/test_songs.py`
- Create: `api/tests/ingest/test_venues.py`

**Step 1: Write failing test for songs**

```python
import json
from pathlib import Path

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.songs import upsert_songs


def test_upsert_songs_inserts_new(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]

    n = upsert_songs(conn, data)
    assert n == 2
    rows = conn.execute("SELECT song_id, name, original_artist FROM songs ORDER BY song_id").fetchall()
    assert rows[0]["song_id"] == 100
    assert rows[0]["name"] == "Chalk Dust Torture"


def test_upsert_songs_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    conn = open_db(tmp_path / "t.db")
    apply_schema(conn)
    data = json.loads((fixtures_dir / "phishnet_songs_sample.json").read_text())["data"]

    upsert_songs(conn, data)
    upsert_songs(conn, data)
    n = conn.execute("SELECT count(*) FROM songs").fetchone()[0]
    assert n == 2
```

**Step 2: Run — expect fail**

**Step 3: Implement**

`api/src/phishpicker/ingest/songs.py`:
```python
import sqlite3
from datetime import datetime, timezone


def upsert_songs(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO songs (song_id, name, original_artist, debut_date, first_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(song_id) DO UPDATE SET
                name = excluded.name,
                original_artist = excluded.original_artist,
                debut_date = excluded.debut_date
            """,
            (r["songid"], r["song"], r.get("artist"), r.get("debut"), now),
        )
        count += 1
    conn.commit()
    return count
```

**Step 4: Run — expect pass**

**Step 5: Repeat for venues** — failing test + impl, mirror the same idempotent pattern. Map `venueid` → `venue_id`, `venue` → `name`, plus `city`, `state`, `country`.

**Step 6: Commit**

```bash
git add api/
git commit -m "feat: idempotent upsert for songs and venues

🤖 assist"
```

---

## Task 7: Ingestion — shows and setlists with derived fields

**Files:**
- Create: `api/src/phishpicker/ingest/shows.py`
- Create: `api/src/phishpicker/ingest/derive.py`
- Create: `api/tests/ingest/test_shows.py`
- Create: `api/tests/ingest/test_derive.py`
- Create: `api/tests/fixtures/phishnet_run_at_msg.json` (4 consecutive MSG shows)

**Step 1: Hand-craft a 4-show MSG run fixture**

Four shows on consecutive dates at venue_id=500. Required to test `run_position` / `run_length`.

**Step 2: Write failing tests for show upsert + setlist upsert**

```python
# api/tests/ingest/test_shows.py
from phishpicker.ingest.shows import upsert_show, upsert_setlist_songs


def test_upsert_show_inserts_new(tmp_path, fixtures_dir):
    # open DB, apply schema, seed venue_id=500, call upsert_show, assert row exists
    ...


def test_upsert_setlist_songs_is_idempotent(tmp_path, fixtures_dir):
    # upsert a 2-song setlist twice; assert only 2 rows and trans_mark preserved
    ...
```

And for derive:

```python
# api/tests/ingest/test_derive.py
from phishpicker.ingest.derive import recompute_run_and_tour_positions


def test_run_position_for_msg_run(tmp_path, fixtures_dir):
    # seed 4 consecutive MSG shows plus a tour id
    # after derive, assert run_position = 1,2,3,4 and run_length = 4 for each
    ...


def test_run_resets_on_non_consecutive_dates(tmp_path):
    # seed 2 shows 30 days apart at same venue
    # after derive, each has run_position=1, run_length=1
    ...
```

**Step 3: Run — expect fail**

**Step 4: Implement**

`api/src/phishpicker/ingest/shows.py`:
```python
import sqlite3
from datetime import datetime, timezone


def upsert_show(conn: sqlite3.Connection, show: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(show_id) DO UPDATE SET
            show_date = excluded.show_date,
            venue_id = excluded.venue_id,
            tour_id = excluded.tour_id,
            fetched_at = excluded.fetched_at
        """,
        (show["showid"], show["showdate"], show.get("venueid"), show.get("tourid"), now),
    )
    conn.commit()


def upsert_setlist_songs(conn: sqlite3.Connection, setlist: list[dict]) -> int:
    count = 0
    for row in setlist:
        conn.execute(
            """
            INSERT INTO setlist_songs (show_id, set_number, position, song_id, trans_mark)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(show_id, set_number, position) DO UPDATE SET
                song_id = excluded.song_id,
                trans_mark = excluded.trans_mark
            """,
            (
                row["showid"],
                str(row["set"]),
                int(row["position"]),
                row["songid"],
                row.get("trans_mark") or ",",
            ),
        )
        count += 1
    conn.commit()
    return count
```

`api/src/phishpicker/ingest/derive.py`:
```python
import sqlite3
from datetime import date


def recompute_run_and_tour_positions(conn: sqlite3.Connection) -> None:
    """Recompute run_position / run_length / tour_position for all shows.

    A 'run' is 2+ consecutive-day shows at the same venue (gap <= 1 day).
    """
    rows = conn.execute(
        "SELECT show_id, show_date, venue_id, tour_id FROM shows "
        "ORDER BY show_date, show_id"
    ).fetchall()

    # compute runs
    runs: dict[int, list[int]] = {}
    current_run: list[tuple[int, str, int]] = []  # (show_id, date, venue_id)

    def flush():
        if not current_run:
            return
        ids = [t[0] for t in current_run]
        run_len = len(ids)
        for pos, sid in enumerate(ids, start=1):
            conn.execute(
                "UPDATE shows SET run_position = ?, run_length = ? WHERE show_id = ?",
                (pos, run_len, sid),
            )

    prev = None
    for r in rows:
        sid, sdate, vid = r["show_id"], r["show_date"], r["venue_id"]
        if prev and prev[2] == vid and (date.fromisoformat(sdate) - date.fromisoformat(prev[1])).days <= 1:
            current_run.append((sid, sdate, vid))
        else:
            flush()
            current_run = [(sid, sdate, vid)]
        prev = (sid, sdate, vid)
    flush()

    # tour positions
    tour_rows = conn.execute(
        "SELECT show_id, tour_id FROM shows WHERE tour_id IS NOT NULL ORDER BY tour_id, show_date, show_id"
    ).fetchall()
    per_tour: dict[int, int] = {}
    for r in tour_rows:
        per_tour[r["tour_id"]] = per_tour.get(r["tour_id"], 0) + 1
        conn.execute(
            "UPDATE shows SET tour_position = ? WHERE show_id = ?",
            (per_tour[r["tour_id"]], r["show_id"]),
        )
    conn.commit()
```

**Step 5: Run — expect pass**

**Step 6: Commit**

```bash
git add api/
git commit -m "feat: show+setlist ingestion with run/tour position derivation

🤖 assist"
```

---

## Task 8: Ingestion orchestrator + CLI

**Files:**
- Create: `api/src/phishpicker/cli.py`
- Create: `api/src/phishpicker/ingest/pipeline.py`
- Create: `api/tests/ingest/test_pipeline.py`

**Step 1: Failing test**

```python
# test_pipeline.py
from pathlib import Path
import json
import pytest
from pytest_httpx import HTTPXMock

from phishpicker.ingest.pipeline import run_full_ingest
from phishpicker.phishnet.client import PhishNetClient
from phishpicker.db.connection import apply_schema, open_db


def test_full_ingest_populates_all_tables(tmp_path, fixtures_dir, httpx_mock: HTTPXMock):
    # mock /songs.json, /venues.json, /shows.json, /setlists/get.json
    # run pipeline against a fresh DB
    # assert: songs > 0, venues > 0, shows > 0, setlist_songs > 0, run_position populated
    ...
```

**Step 2: Run — expect fail**

**Step 3: Implement pipeline**

`api/src/phishpicker/ingest/pipeline.py`:
```python
import sqlite3
from phishpicker.db.connection import apply_schema
from phishpicker.phishnet.client import PhishNetClient
from phishpicker.ingest.songs import upsert_songs
from phishpicker.ingest.venues import upsert_venues
from phishpicker.ingest.shows import upsert_show, upsert_setlist_songs
from phishpicker.ingest.derive import recompute_run_and_tour_positions


def run_full_ingest(conn: sqlite3.Connection, client: PhishNetClient) -> dict:
    apply_schema(conn)

    songs = client.fetch_songs()
    n_songs = upsert_songs(conn, songs)

    venues = client.fetch_venues()
    n_venues = upsert_venues(conn, venues)

    shows = client.fetch_shows_since("1900-01-01")
    n_shows = 0
    n_setlist = 0
    for show in shows:
        upsert_show(conn, show)
        setlist = client.fetch_setlist(show["showid"])
        n_setlist += upsert_setlist_songs(conn, setlist)
        n_shows += 1

    recompute_run_and_tour_positions(conn)
    return {"songs": n_songs, "venues": n_venues, "shows": n_shows, "setlist_rows": n_setlist}
```

**Step 4: Implement CLI**

`api/src/phishpicker/cli.py`:
```python
import argparse
import sys

from phishpicker.config import Settings
from phishpicker.db.connection import open_db, apply_schema, apply_live_schema
from phishpicker.ingest.pipeline import run_full_ingest
from phishpicker.phishnet.client import PhishNetClient


def main() -> int:
    parser = argparse.ArgumentParser(prog="phishpicker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="initialize local sqlite databases")
    sub.add_parser("ingest", help="full phish.net ingest")
    args = parser.parse_args()

    s = Settings()  # type: ignore[call-arg]

    if args.cmd == "init-db":
        conn = open_db(s.db_path)
        apply_schema(conn)
        live = open_db(s.live_db_path)
        apply_live_schema(live)
        print(f"Initialized {s.db_path} and {s.live_db_path}")
        return 0

    if args.cmd == "ingest":
        client = PhishNetClient(api_key=s.phishnet_api_key, base_url=s.phishnet_base_url)
        conn = open_db(s.db_path)
        stats = run_full_ingest(conn, client)
        print(f"Ingest complete: {stats}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 5: Manual validation**

```bash
cd api
uv run phishpicker init-db
# Do NOT run full ingest yet against production phish.net — save for later when you're ready
```

**Step 6: Commit**

```bash
git add api/
git commit -m "feat: ingestion pipeline orchestrator and cli

🤖 assist"
```

---

## Task 9: Heuristic scorer — base rate + recency

**Files:**
- Create: `api/src/phishpicker/model/__init__.py`
- Create: `api/src/phishpicker/model/heuristic.py`
- Create: `api/tests/model/test_heuristic.py`

**Heuristic math (for the walking skeleton):**

For each candidate song not played tonight:

```
score = base_rate * recency_multiplier * venue_multiplier * run_multiplier * role_fit
```

Where:
- `base_rate`: `log(1 + times_played_last_12mo)` — punishes never-played, dampens superstars.
- `recency_multiplier`: `1 - exp(-shows_since_last_played / 30)` — songs played more recently are down-weighted; hits ~1.0 after ~90 shows.
- `venue_multiplier`: `1.0 + 0.5 * (1 - exp(-shows_since_last_here / 20))` — big boost if they haven't played this venue recently.
- `run_multiplier`: if played earlier in the same run, × 0.05. Otherwise × 1.0. (Complements the hard rule.)
- `role_fit`: depends on current_set:
  - if set_position == 1 and set_number == '1' → `opener_score`
  - if set_number == 'E' → `encore_score`
  - else → `0.3 + 0.7 * middle_score` (flat-ish)

All multipliers clamp to [0.01, 10.0]. Final rankings use the raw score; UI normalizes to pseudo-probabilities via softmax.

**Step 1: Failing test**

```python
# test_heuristic.py
def test_base_rate_higher_for_more_played_song():
    from phishpicker.model.heuristic import base_rate
    assert base_rate(times_played_last_12mo=0) < base_rate(times_played_last_12mo=20)


def test_recency_multiplier_small_when_recently_played():
    from phishpicker.model.heuristic import recency_multiplier
    assert recency_multiplier(shows_since_last=1) < recency_multiplier(shows_since_last=100)


def test_run_multiplier_penalizes_repeats():
    from phishpicker.model.heuristic import run_multiplier
    assert run_multiplier(played_already_this_run=True) < 0.1
    assert run_multiplier(played_already_this_run=False) == 1.0
```

And an integration-flavored test that scores a small fixture context:

```python
def test_score_orders_candidates_reasonably(tmp_path):
    # set up 2 songs: one played a lot + long since last played, one played once + recently
    # call score_candidates(...) and assert the stale-popular one ranks higher
    ...
```

**Step 2: Run — expect fail**

**Step 3: Implement `heuristic.py`**

```python
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SongStats:
    song_id: int
    times_played_last_12mo: int
    shows_since_last_played_anywhere: int | None     # None = never played
    shows_since_last_played_here: int | None
    played_already_this_run: bool
    opener_score: float
    encore_score: float
    middle_score: float


@dataclass(frozen=True)
class Context:
    current_set: str            # '1','2','3','E'
    current_position: int       # next slot we're filling (1 = opener)


def base_rate(times_played_last_12mo: int) -> float:
    return math.log1p(times_played_last_12mo)


def recency_multiplier(shows_since_last: int | None) -> float:
    if shows_since_last is None:
        return 1.0
    return 1.0 - math.exp(-shows_since_last / 30.0)


def venue_multiplier(shows_since_last_here: int | None) -> float:
    if shows_since_last_here is None:
        return 1.2
    return 1.0 + 0.5 * (1.0 - math.exp(-shows_since_last_here / 20.0))


def run_multiplier(played_already_this_run: bool) -> float:
    return 0.05 if played_already_this_run else 1.0


def role_fit(stats: SongStats, ctx: Context) -> float:
    if ctx.current_set == "E":
        return 0.2 + stats.encore_score
    if ctx.current_set == "1" and ctx.current_position == 1:
        return 0.2 + stats.opener_score
    return 0.3 + 0.7 * stats.middle_score


def score(stats: SongStats, ctx: Context) -> float:
    raw = (
        base_rate(stats.times_played_last_12mo)
        * recency_multiplier(stats.shows_since_last_played_anywhere)
        * venue_multiplier(stats.shows_since_last_played_here)
        * run_multiplier(stats.played_already_this_run)
        * role_fit(stats, ctx)
    )
    return max(0.0, raw)
```

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: heuristic song scorer with base rate, recency, venue, run, role

🤖 assist"
```

---

## Task 10: Stats extractor (reads DB → SongStats for each candidate)

**Files:**
- Create: `api/src/phishpicker/model/stats.py`
- Create: `api/tests/model/test_stats.py`

This task wires DB aggregate queries into the `SongStats` dataclass used by the scorer. Keep the queries straightforward — no joins across many tables, small batched SELECTs.

**Step 1: Failing test using seeded DB**

```python
def test_compute_song_stats_for_single_song(tmp_path):
    # seed DB with:
    #   songs: song_id=100, "Chalk Dust Torture"
    #   venues: 500 MSG
    #   3 MSG shows in a row, song played in show 1 only
    #   1 other venue show 90 days prior, song not played
    # call compute_song_stats(conn, context_show_id=<show 3>, song_ids=[100])
    # assert: shows_since_last_played_here = 2, played_already_this_run = True, etc.
    ...
```

**Step 2: Run — expect fail**

**Step 3: Implement**

`api/src/phishpicker/model/stats.py`:
```python
import sqlite3
from datetime import date
from phishpicker.model.heuristic import SongStats


def compute_song_stats(
    conn: sqlite3.Connection,
    context_show_id: int,
    song_ids: list[int],
) -> dict[int, SongStats]:
    """Compute SongStats for `song_ids` as of `context_show_id` (i.e. using only
    shows with show_date < context show's date, plus any songs already played
    tonight via live.db — passed separately in Task 13)."""
    ctx = conn.execute(
        "SELECT show_date, venue_id, run_position, run_length FROM shows WHERE show_id = ?",
        (context_show_id,),
    ).fetchone()
    assert ctx, f"Unknown show_id: {context_show_id}"
    ctx_date, ctx_venue = ctx["show_date"], ctx["venue_id"]

    placeholders = ",".join("?" * len(song_ids))

    # counts in last 365 days before context
    last_12mo_counts = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(*) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders})
              AND s.show_date < ?
              AND s.show_date >= date(?, '-1 year')
            GROUP BY ss.song_id
            """,
            [*song_ids, ctx_date, ctx_date],
        ).fetchall()
    )

    # shows since last played anywhere
    last_played_anywhere = dict(
        conn.execute(
            f"""
            SELECT song_id, MAX(show_date) AS last_date
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE song_id IN ({placeholders}) AND show_date < ?
            GROUP BY song_id
            """,
            [*song_ids, ctx_date],
        ).fetchall()
    )

    # shows since last played at THIS venue
    last_played_here = dict(
        conn.execute(
            f"""
            SELECT song_id, MAX(show_date) AS last_date
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE song_id IN ({placeholders}) AND show_date < ? AND s.venue_id = ?
            GROUP BY song_id
            """,
            [*song_ids, ctx_date, ctx_venue],
        ).fetchall()
    )

    # compute shows_since_last (count of shows between last_date and ctx_date)
    def shows_between(from_date: str) -> int:
        r = conn.execute(
            "SELECT COUNT(*) FROM shows WHERE show_date > ? AND show_date < ?",
            (from_date, ctx_date),
        ).fetchone()
        return int(r[0])

    # song-role rates
    role_rows = conn.execute(
        f"""
        SELECT
            song_id,
            SUM(CASE WHEN set_number='1' AND position=1 THEN 1 ELSE 0 END) AS opener,
            SUM(CASE WHEN set_number='E' THEN 1 ELSE 0 END) AS encore,
            COUNT(*) AS total
        FROM setlist_songs
        WHERE song_id IN ({placeholders})
        GROUP BY song_id
        """,
        song_ids,
    ).fetchall()
    roles = {
        r["song_id"]: {
            "opener": (r["opener"] or 0) / max(1, r["total"] or 1),
            "encore": (r["encore"] or 0) / max(1, r["total"] or 1),
            "middle": 1.0 - ((r["opener"] or 0) + (r["encore"] or 0)) / max(1, r["total"] or 1),
        }
        for r in role_rows
    }

    # played_already_this_run: any song_id on shows sharing the same run (venue + consecutive)
    # for walking skeleton: use run_position != null and same venue + run_length window
    played_this_run = set()
    rp = ctx["run_position"]
    rl = ctx["run_length"]
    if rp and rl and rp > 1:
        # grab other shows in same run (same venue, earlier show_date within rl-1 days)
        played_this_run = {
            r["song_id"]
            for r in conn.execute(
                """
                SELECT DISTINCT ss.song_id FROM setlist_songs ss JOIN shows s USING (show_id)
                WHERE s.venue_id = ? AND s.show_date < ?
                  AND s.show_date >= date(?, ?)
                """,
                (ctx_venue, ctx_date, ctx_date, f"-{rl} days"),
            ).fetchall()
        }

    result = {}
    for sid in song_ids:
        last_anywhere = last_played_anywhere.get(sid, {}).get("last_date") if sid in last_played_anywhere else None
        last_here = last_played_here.get(sid, {}).get("last_date") if sid in last_played_here else None
        r = roles.get(
            sid, {"opener": 0.0, "encore": 0.0, "middle": 0.0}
        )
        result[sid] = SongStats(
            song_id=sid,
            times_played_last_12mo=last_12mo_counts.get(sid, 0),
            shows_since_last_played_anywhere=shows_between(last_anywhere) if last_anywhere else None,
            shows_since_last_played_here=shows_between(last_here) if last_here else None,
            played_already_this_run=sid in played_this_run,
            opener_score=r["opener"],
            encore_score=r["encore"],
            middle_score=r["middle"],
        )
    return result
```

**Perf note:** this is intentionally simple. If `/predict` latency exceeds target (<100ms for ~950 songs), revisit with precomputed feature tables per show. For the skeleton, correctness > speed.

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: sqlite-backed stats extractor for the heuristic scorer

🤖 assist"
```

---

## Task 11: Hard-rule post-processor

**Files:**
- Create: `api/src/phishpicker/model/rules.py`
- Create: `api/tests/model/test_rules.py`

**Step 1: Failing tests**

```python
def test_rule_zeros_already_played_tonight():
    from phishpicker.model.rules import apply_post_rules
    scored = [(100, 5.0), (101, 3.0), (102, 2.0)]
    out = apply_post_rules(scored, played_tonight={101})
    assert dict(out)[101] == 0.0
    assert dict(out)[100] == 5.0
```

**Step 2: Run — expect fail**

**Step 3: Implement**

```python
def apply_post_rules(
    scored: list[tuple[int, float]], played_tonight: set[int]
) -> list[tuple[int, float]]:
    return [(sid, 0.0 if sid in played_tonight else s) for sid, s in scored]
```

(For the skeleton, `run_multiplier` in the scorer already handles played-this-run, so the hard-rule layer is deliberately thin. Expand later.)

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: post-scoring hard-rule filter

🤖 assist"
```

---

## Task 12: FastAPI app scaffold + /meta

**Files:**
- Create: `api/src/phishpicker/app.py`
- Create: `api/tests/api/test_meta.py`

**Step 1: Failing test**

```python
# test_meta.py
from fastapi.testclient import TestClient


def test_meta_returns_expected_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    # init dbs
    from phishpicker.db.connection import open_db, apply_schema, apply_live_schema
    apply_schema(open_db(tmp_path / "phishpicker.db"))
    apply_live_schema(open_db(tmp_path / "live.db"))

    from phishpicker.app import create_app
    client = TestClient(create_app())
    r = client.get("/meta")
    assert r.status_code == 200
    body = r.json()
    assert {"shows_count", "songs_count", "data_snapshot_at"} <= set(body)
```

**Step 2: Run — expect fail**

**Step 3: Implement**

`api/src/phishpicker/app.py`:
```python
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI

from phishpicker.config import Settings
from phishpicker.db.connection import open_db


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.read_conn = open_db(settings.db_path, read_only=True)
        app.state.live_conn = open_db(settings.live_db_path)
        yield
        app.state.read_conn.close()
        app.state.live_conn.close()

    app = FastAPI(title="Phishpicker", lifespan=lifespan)

    @app.get("/meta")
    def meta():
        conn = app.state.read_conn
        shows = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
        songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        latest = conn.execute("SELECT MAX(show_date) FROM shows").fetchone()[0]
        return {
            "shows_count": shows,
            "songs_count": songs,
            "latest_show_date": latest,
            "data_snapshot_at": datetime.now(timezone.utc).isoformat(),
            "version": "0.1.0-skeleton",
        }

    return app
```

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: fastapi app with /meta endpoint

🤖 assist"
```

---

## Task 13: /songs + live-show endpoints

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Create: `api/src/phishpicker/live.py` (DB helpers for live show state)
- Create: `api/tests/api/test_songs.py`
- Create: `api/tests/api/test_live.py`

**Step 1: Failing tests (abbreviated — one per endpoint)**

```python
# /songs returns catalog
def test_songs_endpoint(seeded_client):
    r = seeded_client.get("/songs")
    assert r.status_code == 200
    assert any(s["name"] == "Chalk Dust Torture" for s in r.json())


# POST /live/show creates a show
def test_create_live_show(seeded_client):
    r = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500})
    assert r.status_code == 200
    sid = r.json()["show_id"]
    r2 = seeded_client.get(f"/live/show/{sid}")
    assert r2.status_code == 200


# POST /live/song appends
def test_append_live_song(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    r = seeded_client.post("/live/song", json={
        "show_id": sid, "song_id": 100, "set_number": "1", "trans_mark": ","
    })
    assert r.status_code == 200
    r2 = seeded_client.get(f"/live/show/{sid}")
    assert len(r2.json()["songs"]) == 1


# DELETE /live/song/last undoes
def test_undo_last_song(seeded_client):
    # create show, add 2 songs, undo, assert 1 song remains
    ...


# POST /live/set-boundary advances
def test_set_boundary(seeded_client):
    # create show, boundary to '2', assert current_set updated
    ...
```

**Step 2: Run — expect fail**

**Step 3: Implement `live.py` + endpoints**

`api/src/phishpicker/live.py` — thin CRUD helpers: `create_live_show`, `get_live_show`, `append_song`, `delete_last_song`, `advance_set`.

In `app.py`, add endpoints with pydantic request models:

```python
class LiveShowCreate(BaseModel):
    show_date: str
    venue_id: int | None = None


class LiveSongAppend(BaseModel):
    show_id: str
    song_id: int
    set_number: str
    trans_mark: str = ","


class SetBoundary(BaseModel):
    show_id: str
    set_number: str
```

Wire to helpers; return JSON.

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: /songs and /live endpoints for show tracking

🤖 assist"
```

---

## Task 14: /predict endpoint — the payoff

**Files:**
- Modify: `api/src/phishpicker/app.py`
- Create: `api/src/phishpicker/predict.py`
- Create: `api/tests/api/test_predict.py`

**Step 1: Failing test**

```python
def test_predict_returns_ranked_candidates(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    r = seeded_client.get(f"/predict/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert "candidates" in body
    assert len(body["candidates"]) >= 10
    # sorted descending
    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_predict_excludes_played_tonight(seeded_client):
    sid = seeded_client.post("/live/show", json={"show_date": "2026-04-16", "venue_id": 500}).json()["show_id"]
    # add song 100
    seeded_client.post("/live/song", json={"show_id": sid, "song_id": 100, "set_number": "1"})
    r = seeded_client.get(f"/predict/{sid}")
    assert all(c["song_id"] != 100 for c in r.json()["candidates"])
```

**Step 2: Run — expect fail**

**Step 3: Implement `predict.py`**

`api/src/phishpicker/predict.py`:
```python
import math
import sqlite3
from phishpicker.model.heuristic import Context, score
from phishpicker.model.stats import compute_song_stats
from phishpicker.model.rules import apply_post_rules


def predict_next(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    live_show_id: str,
    top_n: int = 20,
) -> list[dict]:
    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (live_show_id,),
    ).fetchone()
    if not show:
        return []

    played = live_conn.execute(
        "SELECT song_id, entered_order, set_number FROM live_songs WHERE show_id = ? ORDER BY entered_order",
        (live_show_id,),
    ).fetchall()
    played_ids = {r["song_id"] for r in played}
    position = sum(1 for r in played if r["set_number"] == show["current_set"]) + 1

    # find/construct a "context_show_id" — for the skeleton, use the most recent
    # historical show at the same venue (if any) to ground stats computations.
    # NOTE: this is a simplification; the real system should build stats relative
    # to the live show's actual date. Revisit when we have feature tables.
    ctx_row = read_conn.execute(
        "SELECT show_id FROM shows WHERE venue_id = ? AND show_date <= ? ORDER BY show_date DESC LIMIT 1",
        (show["venue_id"], show["show_date"]),
    ).fetchone()
    if not ctx_row:
        ctx_row = read_conn.execute(
            "SELECT show_id FROM shows ORDER BY show_date DESC LIMIT 1"
        ).fetchone()
    context_show_id = ctx_row["show_id"]

    song_ids = [r["song_id"] for r in read_conn.execute("SELECT song_id FROM songs").fetchall()]
    stats = compute_song_stats(read_conn, context_show_id, song_ids)
    ctx = Context(current_set=show["current_set"], current_position=position)

    scored = [(sid, score(stats[sid], ctx)) for sid in song_ids]
    scored = apply_post_rules(scored, played_tonight=played_ids)
    scored.sort(key=lambda x: x[1], reverse=True)

    # softmax-normalize top 200 for display
    top = scored[:200]
    if top:
        max_s = top[0][1]
        exps = [math.exp((s - max_s) / max(1e-6, max_s)) for _, s in top]
        total = sum(exps) or 1.0
        normalized = [(sid, s, e / total) for (sid, s), e in zip(top, exps)]
    else:
        normalized = []

    names = dict(
        read_conn.execute(
            f"SELECT song_id, name FROM songs WHERE song_id IN ({','.join('?' * len(song_ids))})",
            song_ids,
        ).fetchall()
    )
    return [
        {"song_id": sid, "name": names.get(sid, f"#{sid}"), "score": s, "probability": p}
        for sid, s, p in normalized[:top_n]
    ]
```

Wire `/predict/{show_id}` endpoint in `app.py` calling `predict_next`.

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
git add api/
git commit -m "feat: /predict endpoint with heuristic scoring and hard-rule filter

🤖 assist"
```

---

## Task 15: Web — proxy routes + song list hook

**Files:**
- Create: `web/src/app/api/[...path]/route.ts` (catchall API proxy)
- Create: `web/src/lib/songs.ts` (client-side song cache + fuzzy search)
- Create: `web/src/lib/songs.test.ts`

**Step 1: Failing test for fuzzy search**

```ts
// songs.test.ts
import { describe, it, expect } from "vitest";
import { searchSongs } from "@/lib/songs";

const songs = [
  { song_id: 100, name: "Chalk Dust Torture" },
  { song_id: 101, name: "Tweezer" },
  { song_id: 102, name: "You Enjoy Myself" },
];

describe("searchSongs", () => {
  it("matches by partial name", () => {
    const hits = searchSongs(songs, "chal");
    expect(hits[0].song_id).toBe(100);
  });
  it("matches abbreviations loosely", () => {
    const hits = searchSongs(songs, "yem");
    expect(hits.some(s => s.song_id === 102)).toBe(true);
  });
});
```

**Step 2: Run — expect fail**

```bash
cd web && npm test
```

**Step 3: Implement**

`web/src/lib/songs.ts`:
```ts
import Fuse from "fuse.js";

export type Song = { song_id: number; name: string };

export function searchSongs(songs: Song[], query: string, limit = 10): Song[] {
  if (!query.trim()) return songs.slice(0, limit);
  const fuse = new Fuse(songs, { keys: ["name"], threshold: 0.4, ignoreLocation: true });
  return fuse.search(query).slice(0, limit).map(r => r.item);
}
```

`web/src/app/api/[...path]/route.ts`:
```ts
import { NextRequest } from "next/server";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

async function proxy(req: NextRequest, path: string[]) {
  const url = `${API}/${path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: Object.fromEntries(req.headers),
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.text(),
  };
  const r = await fetch(url, init);
  return new Response(r.body, { status: r.status, headers: r.headers });
}

export const GET = (r: NextRequest, { params }: { params: { path: string[] } }) =>
  proxy(r, params.path);
export const POST = GET;
export const DELETE = GET;
export const PUT = GET;
```

**Step 4: Run — expect pass**

**Step 5: Commit**

```bash
cd ..
git add web/
git commit -m "feat: web proxy routes and fuzzy song search

🤖 assist"
```

---

## Task 16: Web — live-show home page, leaderboard, add-song sheet

**Files:**
- Modify: `web/src/app/page.tsx`
- Create: `web/src/components/Leaderboard.tsx`
- Create: `web/src/components/PlayedStrip.tsx`
- Create: `web/src/components/AddSongSheet.tsx`
- Create: `web/src/components/SetBoundaryButton.tsx`
- Create: `web/src/lib/liveShow.ts` (client-side hook for live show state)
- Create: `web/src/components/Leaderboard.test.tsx`

This is the biggest UI task. Build components in order: Leaderboard first (renders static top-N), then the page that fetches data, then AddSongSheet last.

**Step 1: Failing component test for Leaderboard**

```tsx
// Leaderboard.test.tsx
import { render, screen } from "@testing-library/react";
import { Leaderboard } from "./Leaderboard";

it("renders top candidates sorted", () => {
  render(<Leaderboard candidates={[
    { song_id: 1, name: "A", probability: 0.3, score: 5 },
    { song_id: 2, name: "B", probability: 0.1, score: 2 },
  ]} />);
  const items = screen.getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("A");
});
```

**Step 2: Run — expect fail**

**Step 3: Implement Leaderboard**

```tsx
// Leaderboard.tsx
export type Candidate = { song_id: number; name: string; probability: number; score: number };

export function Leaderboard({ candidates }: { candidates: Candidate[] }) {
  return (
    <ol className="space-y-1">
      {candidates.map(c => (
        <li key={c.song_id} className="flex items-center gap-3 py-2">
          <span className="text-neutral-400 w-8 tabular-nums">
            {(c.probability * 100).toFixed(0)}%
          </span>
          <div className="flex-1">
            <div>{c.name}</div>
            <div className="h-1 bg-neutral-800 rounded overflow-hidden mt-1">
              <div
                className="h-full bg-indigo-500"
                style={{ width: `${Math.min(100, c.probability * 100)}%` }}
              />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
```

**Step 4: Implement `page.tsx`**

Client component that:
1. On mount: GET `/api/songs` (cache in state + localStorage keyed by version).
2. On mount: check localStorage for active `live_show_id`; if present, use it. Otherwise show "Start show" button → prompts for date + venue → POST `/api/live/show`.
3. SWR polls `/api/predict/{show_id}` every 10s.
4. Renders: header (venue/date/set), `<Leaderboard>`, `<PlayedStrip>`, `<AddSongSheet>`, `<SetBoundaryButton>`.

**Step 5: Implement `AddSongSheet`**

Bottom sheet with:
- Search input (auto-focus when opened)
- Results list from `searchSongs(songs, query)`
- Tap a song → POST `/api/live/song` → close sheet → invalidate predict cache

**Step 6: Implement `PlayedStrip`** + undo: horizontal scrolling list, tap a song → confirm undo → DELETE `/api/live/song/last` (skeleton implementation only undoes the last entry — good enough for v1).

**Step 7: Run component tests**

```bash
cd web && npm test
```

**Step 8: Manual smoke**

```bash
# in api/
uv run uvicorn phishpicker.app:create_app --factory --reload
# in web/
npm run dev
# visit http://localhost:3000, start a show, add a song, watch leaderboard re-rank
```

**Step 9: Commit**

```bash
cd ..
git add web/
git commit -m "feat: live-show UI — leaderboard, played strip, add-song sheet, set boundary

🤖 assist"
```

---

## Task 17: Dockerfiles + docker-compose stack

**Files:**
- Create: `api/Dockerfile`
- Create: `web/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Step 1: `.dockerignore`**

```
.git
.venv
node_modules
.next
*.db
data/
.env
.env.local
```

**Step 2: `api/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY src ./src
RUN uv sync --no-dev

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH" PHISHPICKER_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "phishpicker.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: `web/Dockerfile`**

```dockerfile
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "start"]
```

**Step 4: `docker-compose.yml`**

```yaml
services:
  api:
    build: ./api
    volumes:
      - /volume/phishpicker/data:/data
    environment:
      PHISHPICKER_DATA_DIR: /data
      PHISHNET_API_KEY: ${PHISHNET_API_KEY}
    networks: [internal]
    restart: unless-stopped

  web:
    build: ./web
    environment:
      API_INTERNAL_URL: http://api:8000
    ports:
      - "3000:3000"
    depends_on: [api]
    networks: [internal]
    restart: unless-stopped

networks:
  internal:
    driver: bridge
```

**Step 5: Local smoke**

```bash
docker compose build
docker compose up
# visit http://localhost:3000 — should load even with empty DB (API /meta returns zeros)
```

**Step 6: Commit**

```bash
git add api/Dockerfile web/Dockerfile docker-compose.yml .dockerignore
git commit -m "chore: dockerize api and web, compose stack

🤖 assist"
```

---

## Task 18: Mac mini ingestion + deploy script

**Files:**
- Create: `scripts/ingest_and_ship.sh`
- Create: `scripts/README.md`

**Step 1: Write the script**

`scripts/ingest_and_ship.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Runs on the mac mini. Pulls from phish.net, atomically ships the sqlite snapshot to the NAS.

REPO_DIR="${REPO_DIR:-$HOME/phishpicker}"
NAS_DATA_DIR="${NAS_DATA_DIR:-/volume/phishpicker/data}"
NAS_HOST="${NAS_HOST:-nas-ssh}"

cd "$REPO_DIR/api"
uv run phishpicker ingest

# atomic ship
STAGING="$NAS_DATA_DIR/phishpicker.db.new"
FINAL="$NAS_DATA_DIR/phishpicker.db"
scp "$REPO_DIR/data/phishpicker.db" "$NAS_HOST:$STAGING"
ssh "$NAS_HOST" "mv '$STAGING' '$FINAL'"

# trigger reload (loopback-only endpoint, fire-and-forget)
ssh "$NAS_HOST" "curl -fsS -X POST http://localhost:8000/internal/reload || true"
echo "shipped: $(date -u +%FT%TZ)"
```

**Step 2: Add `/internal/reload` endpoint**

Modify `app.py` — add a POST route that closes & re-opens `app.state.read_conn`. Guard it so it only responds to 127.0.0.1 (check `request.client.host`).

**Step 3: Manual validation (requires real phish.net access + NAS SSH)**

```bash
bash scripts/ingest_and_ship.sh
# verify /volume/phishpicker/data/phishpicker.db was updated on NAS
```

**Step 4: Commit**

```bash
git add scripts/ api/src/phishpicker/app.py
git commit -m "feat: mac mini ingest-and-ship script with atomic rename + reload

🤖 assist"
```

---

## Task 19: Deployment docs (Cloudflare tunnel + Authentik)

**Files:**
- Create: `docs/deploy.md`

Document (not automate — one-time setup):

1. **NAS directory setup**: create `/volume/phishpicker/data`, ensure compose user can read.
2. **First deploy**: `scp` the repo to `nas-ssh:~/phishpicker`, `docker compose up -d` from there.
3. **Cloudflare tunnel**: add a `cloudflared` route mapping `phishpicker.<domain>` → `http://<nas-ip>:3000`. Walk through the tunnel config file change.
4. **Authentik**: create a proxy provider + application in Authentik pointing at the tunnel subdomain. Enforce auth. Test sign-in.
5. **SSH key for Mac mini → NAS** (per design doc prereqs): generate, authorize, verify `ssh nas-ssh` works without prompt from Mac mini.
6. **Schedule**: cron entry on Mac mini — `0 * * * * /home/david/phishpicker/scripts/ingest_and_ship.sh >> /var/log/phishpicker-ingest.log 2>&1`.

**Commit:**

```bash
git add docs/deploy.md
git commit -m "docs: cloudflare + authentik + cron deployment notes

🤖 assist"
```

---

## Task 20: End-to-end smoke validation

No new files. Manual run-through — the plan isn't done until this checklist passes.

**Checklist:**

- [ ] `docker compose up -d` on NAS, visit through Cloudflare tunnel, sign in via Authentik.
- [ ] `/meta` returns non-zero `shows_count` (run the ingest on Mac mini once if needed).
- [ ] From phone browser: Start a live show with today's date + a real venue.
- [ ] Song type-ahead: type "chal" — "Chalk Dust Torture" appears.
- [ ] Add 3 songs — leaderboard re-ranks each time.
- [ ] Tap played-strip song → undo confirmed → song removed.
- [ ] Hit set boundary → leaderboard changes (openers deprioritized).
- [ ] Model-meta line at page footer shows recent timestamp.
- [ ] Refresh mid-show — state persists.
- [ ] Prediction latency: predict response <500ms on NAS (slower than design target is fine for skeleton).

If all checks pass, commit a tag:

```bash
git tag -a v0.1.0-skeleton -m "Walking skeleton complete"
```

---

## Definition of done for this plan

- All 20 tasks committed.
- `docker compose up -d` on NAS produces a working UI behind Cloudflare + Authentik.
- A live show can be created, songs added with type-ahead, leaderboard re-ranks.
- Mac mini cron runs ingestion and ships updates atomically.
- Design-doc `metrics targets` are NOT part of this plan's done criteria — this ships the heuristic, not the ML model. Metrics land in the next plan.

## Next plans (not in this plan)

After the skeleton ships, write separate plans for:

1. **LightGBM model** — feature engineering, training pipeline, walk-forward eval, ship gate, metrics display in `/about`.
2. **Bust-out watch** — UI sidebar, backend endpoint.
3. **Show archive + replay** — historical browsing, model-vs-truth view.
4. **Jam-length model** — secondary regression head + UI badges.
5. **Automated in-show ingestion** — phish.net polling, websocket push.
