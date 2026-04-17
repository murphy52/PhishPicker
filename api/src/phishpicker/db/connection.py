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


def apply_live_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(LIVE_SCHEMA_PATH.read_text())
    conn.commit()
