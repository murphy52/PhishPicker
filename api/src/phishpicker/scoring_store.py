"""Persistence + capture for the scoring game (live_score_state).

The engine (scoring.py) is pure; this module owns the captured inputs:
the frozen pre-show bracket and the per-entry prediction snapshots.
"""

import contextlib
import json
import logging
import sqlite3
from datetime import UTC, datetime

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextlib.contextmanager
def _immediate(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE around a read-modify-write so the manual entry path
    and the sync poller (different connections) can't interleave and drop a
    snapshot. Tolerates already being inside a transaction."""
    started = True
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        started = False  # caller already holds a transaction
    try:
        yield
        if started:
            conn.commit()
    except Exception:
        if started:
            conn.rollback()
        raise


def get_score_state(live_conn: sqlite3.Connection, show_id: str) -> dict | None:
    row = live_conn.execute(
        "SELECT show_id, model_sha, frozen_bracket, snapshots, updated_at "
        "FROM live_score_state WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "show_id": row["show_id"],
        "model_sha": row["model_sha"],
        "frozen_bracket": (
            json.loads(row["frozen_bracket"]) if row["frozen_bracket"] else None
        ),
        "snapshots": json.loads(row["snapshots"] or "[]"),
        "updated_at": row["updated_at"],
    }


def upsert_score_state(
    live_conn: sqlite3.Connection,
    show_id: str,
    *,
    model_sha: str | None = None,
    frozen_bracket: list[dict] | None = None,
) -> None:
    live_conn.execute(
        "INSERT INTO live_score_state (show_id, model_sha, frozen_bracket, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(show_id) DO UPDATE SET "
        "model_sha = excluded.model_sha, "
        "frozen_bracket = excluded.frozen_bracket, "
        "updated_at = excluded.updated_at",
        (
            show_id,
            model_sha,
            json.dumps(frozen_bracket) if frozen_bracket is not None else None,
            _now(),
        ),
    )
    live_conn.commit()


def append_snapshot(
    live_conn: sqlite3.Connection, show_id: str, snapshot: dict
) -> None:
    with _immediate(live_conn):
        row = live_conn.execute(
            "SELECT snapshots FROM live_score_state WHERE show_id = ?", (show_id,)
        ).fetchone()
        if row is None:
            live_conn.execute(
                "INSERT INTO live_score_state (show_id, snapshots, updated_at) "
                "VALUES (?, ?, ?)",
                (show_id, json.dumps([snapshot]), _now()),
            )
            return
        snapshots = json.loads(row["snapshots"] or "[]")
        snapshots.append(snapshot)
        live_conn.execute(
            "UPDATE live_score_state SET snapshots = ?, updated_at = ? "
            "WHERE show_id = ?",
            (json.dumps(snapshots), _now(), show_id),
        )
