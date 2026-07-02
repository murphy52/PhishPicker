"""Glue between stored state and the pure engine: load live_songs +
live_score_state, derive the engine inputs, run score_show. Recompute-on-read —
the model is never re-run here (capture-don't-recompute)."""

import sqlite3

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

    song_ids = {r["song_id"] for r in actual}
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

    result = score_show(
        bracket,
        actual,
        _next_call_by_index(snapshots, len(actual)),
        early_called_indices=_early_called_indices(snapshots, actual),
        bustout_song_ids=bustout_song_ids,
    )
    for att in result["attributions"]:
        att["name"] = names.get(att["song_id"], f"#{att['song_id']}")
    result["model_sha"] = state.get("model_sha")
    result["frozen"] = bool(bracket)
    return result
