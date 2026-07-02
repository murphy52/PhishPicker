"""Glue between stored state and the pure engine: load live_songs +
live_score_state, derive the engine inputs, run score_show. Recompute-on-read —
the model is never re-run here (capture-don't-recompute)."""

import json
import sqlite3
from datetime import UTC, datetime

from phishpicker.scoring import normalize_setlist, score_show
from phishpicker.scoring_store import get_score_state


def _actual_setlist(live_conn: sqlite3.Connection, show_id: str) -> list[dict]:
    """live_songs rows -> normalized setlist with a derived 1-based
    position-within-set (rows only know their entered_order)."""
    rows = live_conn.execute(
        "SELECT song_id, set_number FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (show_id,),
    ).fetchall()
    counter: dict[str, int] = {}
    out = []
    for r in rows:
        s = r["set_number"]
        counter[s] = counter.get(s, 0) + 1
        out.append({"set_number": s, "position": counter[s], "song_id": r["song_id"]})
    return normalize_setlist(out)


def _next_call_by_index(snapshots: list[dict], n: int) -> dict[int, int]:
    """For actual index i>=1, the #1 pick of the LAST snapshot (append order)
    with after_count == i — corrections/set-advances create duplicates, and
    the last one is what was on screen when actual[i] revealed. No matching
    snapshot -> key omitted (a no-event for the combo)."""
    calls: dict[int, int] = {}
    by_count: dict[int, dict] = {}
    for snap in snapshots:  # later snapshots overwrite: last-wins
        by_count[snap["after_count"]] = snap
    for i in range(1, n):
        snap = by_count.get(i)
        if snap and snap["remaining"]:
            calls[i] = snap["remaining"][0]["song_id"]
    return calls


def _early_called_indices(snapshots: list[dict], actual: list[dict]) -> set[int]:
    """Actual indices the model had correctly placed (exact set+position)
    in a snapshot made 2+ reveals earlier — the 0-pt lookahead badge."""
    early: set[int] = set()
    for i in range(2, len(actual)):
        row = actual[i]
        key = (row["set_number"], row["position"], row["song_id"])
        for snap in snapshots:
            if snap["after_count"] > i - 2:
                continue
            if any(
                (e["set_number"], e["position"], e["song_id"]) == key
                for e in snap["remaining"]
            ):
                early.add(i)
                break
    return early


def score_live_show(
    read_conn: sqlite3.Connection, live_conn: sqlite3.Connection, show_id: str
) -> dict:
    actual = _actual_setlist(live_conn, show_id)
    state = get_score_state(live_conn, show_id) or {}
    bracket = state.get("frozen_bracket") or []
    snapshots = state.get("snapshots") or []

    # Resolve names for the actual setlist AND the frozen bracket — the
    # predicted-setlist view renders every pick, including 'absent' ones that
    # never played and so aren't in the actual setlist.
    song_ids = {r["song_id"] for r in actual} | {p["song_id"] for p in bracket}
    bustout_song_ids = set()
    names: dict[int, str] = {}
    if song_ids:
        placeholders = ",".join("?" * len(song_ids))
        for r in read_conn.execute(
            f"SELECT song_id, name, is_bustout_placeholder FROM songs "
            f"WHERE song_id IN ({placeholders})",
            list(song_ids),
        ).fetchall():
            names[r["song_id"]] = r["name"]
            if r["is_bustout_placeholder"]:
                bustout_song_ids.add(r["song_id"])

    def _name(sid: int) -> str:
        return names.get(sid, f"#{sid}")

    result = score_show(
        bracket,
        actual,
        _next_call_by_index(snapshots, len(actual)),
        early_called_indices=_early_called_indices(snapshots, actual),
        bustout_song_ids=bustout_song_ids,
    )
    for att in result["attributions"]:
        att["name"] = _name(att["song_id"])
    for outcome in result["pick_outcomes"]:
        outcome["name"] = _name(outcome["pick"]["song_id"])
    result["model_sha"] = state.get("model_sha")
    result["frozen"] = bool(bracket)
    return result


def finalize_scorecard(
    read_conn: sqlite3.Connection, live_conn: sqlite3.Connection, show_id: str
) -> dict:
    """Run the same engine over the final setlist and persist the totals.
    Idempotent — re-finalizing (e.g. after a late phish.net correction)
    recomputes and overwrites the row. Returns the scorecard plus cross-show
    "best yet?" context."""
    show = live_conn.execute(
        "SELECT show_date FROM live_show WHERE show_id = ?", (show_id,)
    ).fetchone()
    if show is None:
        raise ValueError(f"unknown live show {show_id}")

    result = score_live_show(read_conn, live_conn, show_id)
    totals = result["totals"]
    max_streak = max((a["streak"] for a in result["attributions"]), default=0)
    card = {
        "show_id": show_id,
        "show_date": show["show_date"],
        "finalized_at": datetime.now(UTC).isoformat(),
        "combined": totals["combined"],
        "foresight_total": totals["foresight_total"],
        "live_total": totals["live_total"],
        "ppps": totals["ppps"],
        "max_streak": max_streak,
    }
    live_conn.execute(
        "INSERT INTO scorecards (show_id, show_date, finalized_at, combined, "
        "foresight_total, live_total, ppps, max_streak, payload) "
        "VALUES (:show_id, :show_date, :finalized_at, :combined, "
        ":foresight_total, :live_total, :ppps, :max_streak, :payload) "
        "ON CONFLICT(show_id) DO UPDATE SET "
        "finalized_at = excluded.finalized_at, combined = excluded.combined, "
        "foresight_total = excluded.foresight_total, "
        "live_total = excluded.live_total, ppps = excluded.ppps, "
        "max_streak = excluded.max_streak, payload = excluded.payload",
        {**card, "payload": json.dumps(result)},
    )
    live_conn.commit()

    stats = live_conn.execute(
        "SELECT COUNT(*) AS n, MAX(combined) AS best_total, MAX(ppps) AS best_ppps, "
        "(SELECT COUNT(*) + 1 FROM scorecards o "
        " WHERE o.combined > s.combined AND o.show_id != s.show_id) AS rank_by_total "
        "FROM scorecards s WHERE s.show_id = ?",
        (show_id,),
    ).fetchone()
    # MAX() above aggregates only the target row; query the table-wide bests.
    bests = live_conn.execute(
        "SELECT COUNT(*) AS n, MAX(combined) AS best_total, MAX(ppps) AS best_ppps "
        "FROM scorecards"
    ).fetchone()
    context = {
        "shows_scored": bests["n"],
        "best_total": bests["best_total"],
        "best_ppps": bests["best_ppps"],
        "rank_by_total": stats["rank_by_total"],
        "is_best": card["combined"] >= (bests["best_total"] or 0),
    }
    return {"scorecard": card, "context": context, "result": result}


def list_scorecards(live_conn: sqlite3.Connection) -> list[dict]:
    rows = live_conn.execute(
        "SELECT show_id, show_date, finalized_at, combined, foresight_total, "
        "live_total, ppps, max_streak FROM scorecards ORDER BY show_date DESC"
    ).fetchall()
    return [dict(r) for r in rows]
