"""Persistence + capture for the scoring game (live_score_state).

The engine (scoring.py) is pure; this module owns the captured inputs:
the frozen pre-show bracket and the per-entry prediction snapshots.
"""

import contextlib
import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime

log = logging.getLogger(__name__)

# Serializes snapshot captures across the whole process. Each capture runs a
# LightGBM inference (predict_next) then a short live.db write. Left
# unserialized, a burst of song entries (manual + the sync poller) would run
# several inferences at once, saturating the low-power NAS CPU and stretching
# the writer's lock hold until other writers time out ("database is locked").
# One capture at a time keeps CPU and the single WAL writer slot uncontended.
_CAPTURE_LOCK = threading.Lock()


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


def _remaining_prediction(read_conn, live_conn, show_id: str, scorer) -> list[dict]:
    """build_preview(top_k=1) reduced to the predicted slots — the model's
    one-song-per-slot forecast of everything not yet played."""
    from phishpicker.live_preview import build_preview

    preview = build_preview(
        read_conn=read_conn, live_conn=live_conn, show_id=show_id, top_k=1, scorer=scorer
    )
    return [
        {
            "set_number": s["set_number"],
            "position": s["position"],
            "song_id": s["top_k"][0]["song_id"],
        }
        for s in preview["slots"]
        if s["state"] == "predicted" and s.get("top_k")
    ]


def ensure_frozen(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    *,
    scorer,
) -> bool:
    """Freeze the pre-show bracket if not already frozen. Returns True when a
    freeze happened.

    MUST run BEFORE the first live_songs insert for the show: build_preview
    reads entered songs from the DB, so a post-insert freeze would return the
    opener as an 'entered' slot and silently drop the 60-pt opener pick.
    """
    state = get_score_state(live_conn, show_id)
    if state is not None and state["frozen_bracket"]:
        return False
    bracket = _remaining_prediction(read_conn, live_conn, show_id, scorer)
    if not bracket:
        log.warning("freeze for %s produced an empty bracket; not storing", show_id)
        return False
    upsert_score_state(
        live_conn, show_id, model_sha=getattr(scorer, "sha", None), frozen_bracket=bracket
    )
    return True


def capture_snapshot(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    *,
    scorer,
) -> bool:
    """Capture the current remaining prediction after a prediction-changing
    event (append, correction, set advance). Multiple snapshots may share an
    after_count (corrections/advances don't change the count) — the reader
    takes the last one in append order.

    Refuses to mix model shas in one scorecard (log + skip, per design).

    CHEAP BY DESIGN: captures only the immediate next-song call (one
    predict_next), not the full remaining setlist. Scoring's
    next_call_by_index only reads remaining[0], and a full build_preview
    (~18 predictions) on every song entry saturated the NAS CPU and made
    add-song take 30s+. The look-ahead badge (which scanned the full
    remaining list) degrades to 1-ahead — it is a 0-point v1 cosmetic.
    """
    import time

    from phishpicker.predict import predict_next

    state = get_score_state(live_conn, show_id)
    sha = getattr(scorer, "sha", None)
    if state is not None and state["model_sha"] and sha != state["model_sha"]:
        log.warning(
            "capture skipped for %s: scorer sha %s != stored %s",
            show_id, sha, state["model_sha"],
        )
        return False
    show = live_conn.execute(
        "SELECT current_set FROM live_show WHERE show_id = ?", (show_id,)
    ).fetchone()
    if show is None:
        return False
    current_set = show["current_set"]
    t0 = time.monotonic()
    # One capture (inference + write) at a time across the process — see
    # _CAPTURE_LOCK. The model call and the read-modify-write of the snapshots
    # blob both live inside the lock so bursts serialize instead of thrashing.
    with _CAPTURE_LOCK:
        after_count = live_conn.execute(
            "SELECT COUNT(*) FROM live_songs WHERE show_id = ?", (show_id,)
        ).fetchone()[0]
        pos_in_set = (
            live_conn.execute(
                "SELECT COUNT(*) FROM live_songs WHERE show_id = ? AND set_number = ?",
                (show_id, current_set),
            ).fetchone()[0]
            + 1
        )
        cands = predict_next(read_conn, live_conn, show_id, top_n=1, scorer=scorer)
        remaining = (
            [
                {
                    "set_number": current_set,
                    "position": pos_in_set,
                    "song_id": cands[0]["song_id"],
                }
            ]
            if cands
            else []
        )
        append_snapshot(
            live_conn, show_id, {"after_count": after_count, "remaining": remaining}
        )
    log.info(
        "captured snapshot for %s (after_count=%d) in %.2fs",
        show_id, after_count, time.monotonic() - t0,
    )
    return True


def capture_snapshot_bg(db_path, live_db_path, show_id: str, scorer) -> None:
    """Open fresh connections and capture — safe as a FastAPI BackgroundTask,
    where the request-scoped connections are already closed by the time the
    task runs. Best-effort: never raises into the background runner."""
    from phishpicker.db.connection import open_db

    try:
        with open_db(db_path, read_only=True) as read, open_db(live_db_path) as live:
            capture_snapshot(read, live, show_id, scorer=scorer)
    except Exception:
        log.warning("background capture failed for %s", show_id, exc_info=True)


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
