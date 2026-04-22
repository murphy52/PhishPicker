import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
LIVE_SCHEMA_PATH = Path(__file__).parent / "live_schema.sql"


def open_db(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults.

    FastAPI dispatches sync generator deps and sync endpoints across
    different threadpool workers, so a connection opened in one worker
    may be used in another. check_same_thread=False makes sqlite3
    tolerate that; per-request connections and WAL mode keep the access
    pattern safe.

    busy_timeout tells SQLite to wait (ms) for a lock instead of raising
    OperationalError("database is locked") immediately — important
    because the phish.net sync poller holds a write transaction while
    reconciling, and a concurrent /preview request would otherwise 500.
    journal_mode=WAL is a persistent DB-file property; we only set it
    when the DB isn't already in WAL to avoid a redundant PRAGMA write
    that itself can fail against a busy DB.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        current = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if current != "wal":
            conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)
    conn.commit()
    for alter in [
        "ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(alter)
            conn.commit()
        except sqlite3.OperationalError:
            pass


def apply_live_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(LIVE_SCHEMA_PATH.read_text())
    conn.commit()
    for alter in [
        "ALTER TABLE live_songs ADD COLUMN source TEXT NOT NULL DEFAULT 'user'",
        "ALTER TABLE live_songs ADD COLUMN superseded_by INTEGER",
    ]:
        try:
            conn.execute(alter)
            conn.commit()
        except sqlite3.OperationalError:
            pass
