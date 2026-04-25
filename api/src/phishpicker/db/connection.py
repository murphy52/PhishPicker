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

    journal_mode=WAL is a persistent DB-file property and is set once by
    apply_schema / apply_live_schema. Touching it on every per-request
    open is unnecessary and the read form (PRAGMA journal_mode) itself
    can return "database is locked" under sync-poller contention even
    with busy_timeout set, so this function deliberately does NOT query
    or set journal_mode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    # WAL is a persistent file-level property; set once at init. Tolerate
    # the rare case where the DB is already busy by leaving the prior mode
    # in place — apply_schema callers run at startup, before traffic.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass


def apply_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)
    conn.commit()
    _enable_wal(conn)
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
    _enable_wal(conn)
    for alter in [
        "ALTER TABLE live_songs ADD COLUMN source TEXT NOT NULL DEFAULT 'user'",
        "ALTER TABLE live_songs ADD COLUMN superseded_by INTEGER",
    ]:
        try:
            conn.execute(alter)
            conn.commit()
        except sqlite3.OperationalError:
            pass
