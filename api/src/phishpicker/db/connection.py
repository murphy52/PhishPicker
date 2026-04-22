import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
LIVE_SCHEMA_PATH = Path(__file__).parent / "live_schema.sql"


def open_db(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        # Don't set journal_mode=WAL on a read-only connection — PRAGMA
        # journal_mode writes to the DB header and fails with
        # 'attempt to write a readonly database'. WAL mode is set once
        # when the DB is written by the ingest pipeline.
        conn.execute("PRAGMA foreign_keys = ON")
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
