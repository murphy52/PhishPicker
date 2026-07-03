import contextlib
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
    OperationalError("database is locked") immediately. Every live.db write
    (append_song, snapshot capture, sync reconcile) is quick — ms-scale — so
    a writer only ever waits when several pile up at once. On the low-power
    NAS a burst (manual entry + the 60s sync poller + a background capture)
    could hold the single WAL writer slot past a short timeout and 500 a
    user's song entry. 15s gives the holders ample room to drain; no
    operation legitimately holds the write lock that long (model inference
    runs outside any transaction), so this never masks a real deadlock.

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
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.row_factory = sqlite3.Row
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    # WAL is a persistent file-level property; set once at init. Tolerate
    # the rare case where the DB is already busy by leaving the prior mode
    # in place — apply_schema callers run at startup, before traffic.
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute("PRAGMA journal_mode = WAL")


def apply_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)
    conn.commit()
    _enable_wal(conn)
    for alter in [
        "ALTER TABLE songs ADD COLUMN is_bustout_placeholder INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE songs ADD COLUMN slug TEXT",
    ]:
        try:
            conn.execute(alter)
            conn.commit()
        except sqlite3.OperationalError:
            pass


def _rename_tables_with_old_set_checks(conn: sqlite3.Connection) -> list[str]:
    """SQLite cannot ALTER a CHECK constraint, so live DBs created before
    E2/E3 support must have live_show/live_songs rebuilt. Rename the stale
    tables aside (legacy mode so FK clauses in other tables keep their
    original text); apply_live_schema's executescript then recreates them
    fresh and _finish_set_check_migration copies the rows back."""
    renamed: list[str] = []
    for table in ("live_show", "live_songs"):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if row is None or "'E2'" in row["sql"]:
            continue
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_migr_old")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        renamed.append(table)
    conn.commit()
    return renamed


def _finish_set_check_migration(conn: sqlite3.Connection, renamed: list[str]) -> None:
    # Copy live_show before live_songs so the FK target exists first.
    for table in ("live_show", "live_songs"):
        if table not in renamed:
            continue
        cols = ", ".join(
            r["name"]
            for r in conn.execute(f"PRAGMA table_info({table}_migr_old)").fetchall()
        )
        conn.execute(
            f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {table}_migr_old"
        )
        conn.execute(f"DROP TABLE {table}_migr_old")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def apply_live_schema(conn: sqlite3.Connection) -> None:
    renamed = _rename_tables_with_old_set_checks(conn)
    conn.executescript(LIVE_SCHEMA_PATH.read_text())
    conn.commit()
    if renamed:
        _finish_set_check_migration(conn, renamed)
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
