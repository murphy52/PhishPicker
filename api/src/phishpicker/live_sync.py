"""Reconcile user-entered live_songs with phish.net's canonical setlist.

Matches by (set_number, within-set-position). Position within a set is derived
from the order of occurrence in `user_rows` (which the caller must pass in
entered_order order). For `net_rows`, we trust phish.net's `position` field.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.live import append_song, get_live_show, replace_song_at
from phishpicker.phishnet.client import PhishNetClient


@dataclass
class ReconcileAction:
    kind: str  # "append" | "override"
    song_id: int
    set_number: str
    position_in_set: int
    old_song_id: int | None = None
    entered_order: int | None = None  # live_songs row; set only for "override"
    is_bustout: bool = False


def _index_by_set_position(
    rows: list[dict], *, position_source: str
) -> dict[tuple[str, int], dict]:
    if position_source == "user":
        out: dict[tuple[str, int], dict] = {}
        counter: dict[str, int] = {}
        for r in rows:
            s = r["set_number"]
            counter[s] = counter.get(s, 0) + 1
            out[(s, counter[s])] = r
        return out
    if position_source == "net":
        return {(r["set_number"], int(r["position"])): r for r in rows}
    raise ValueError(position_source)


def reconcile(
    user_rows: list[dict], net_rows: list[dict]
) -> list[ReconcileAction]:
    user_by_key = _index_by_set_position(user_rows, position_source="user")
    net_by_key = _index_by_set_position(net_rows, position_source="net")

    actions: list[ReconcileAction] = []
    for (set_number, pos), net in sorted(net_by_key.items()):
        user = user_by_key.get((set_number, pos))
        if user is None:
            actions.append(
                ReconcileAction(
                    kind="append",
                    song_id=net["song_id"],
                    set_number=set_number,
                    position_in_set=pos,
                    is_bustout=bool(net.get("is_unknown")),
                )
            )
            continue
        if user["song_id"] == net["song_id"]:
            continue
        actions.append(
            ReconcileAction(
                kind="override",
                song_id=net["song_id"],
                set_number=set_number,
                position_in_set=pos,
                old_song_id=user["song_id"],
                entered_order=user["entered_order"],
                is_bustout=bool(net.get("is_unknown")),
            )
        )
    return actions


def _resolve_or_insert_song(read_conn, net_row: dict) -> tuple[int, bool]:
    """Find a local song_id for a phish.net song; insert a bustout placeholder
    if the name is unknown. Returns (song_id, is_unknown)."""
    name = net_row.get("song", "")
    row = read_conn.execute(
        "SELECT song_id, is_bustout_placeholder FROM songs WHERE name = ?",
        (name,),
    ).fetchone()
    if row:
        return row["song_id"], bool(row["is_bustout_placeholder"])
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cur = read_conn.execute(
        "INSERT INTO songs (name, first_seen_at, is_bustout_placeholder) "
        "VALUES (?, ?, 1)",
        (name, now),
    )
    read_conn.commit()
    return cur.lastrowid, True


def sync_show_with_phishnet(
    *,
    db_path: Path,
    live_db_path: Path,
    api_key: str,
    show_id: str,
    show_date: str,
) -> dict:
    """Idempotent reconcile of live_songs with phish.net's current setlist.

    Opens its OWN connections each call — this function is safe to call
    from an asyncio worker thread; do NOT pass connections in.
    """
    with PhishNetClient(api_key) as client:
        net_raw = client.fetch_setlist_by_date(show_date)

    with open_db(db_path, read_only=False) as read_rw, open_db(live_db_path) as live:
        net_rows: list[dict] = []
        for r in net_raw:
            sid, is_unknown = _resolve_or_insert_song(read_rw, r)
            net_rows.append(
                {
                    "song_id": sid,
                    "set_number": str(r["set"]).upper(),
                    "position": int(r["position"]),
                    "is_unknown": is_unknown,
                }
            )

        live_show = get_live_show(live, show_id)
        if not live_show:
            return {
                "status": "no-show",
                "appended": 0,
                "overrides": 0,
                "bustouts": 0,
                "last_updated": None,
            }

        user_rows = [
            {
                "song_id": s["song_id"],
                "set_number": s["set_number"],
                "entered_order": s["entered_order"],
            }
            for s in live_show["songs"]
        ]
        actions = reconcile(user_rows, net_rows)

        appended = overrides = bustouts = 0
        for a in actions:
            if a.kind == "append":
                append_song(live, show_id, a.song_id, a.set_number)
                appended += 1
            else:
                replace_song_at(
                    live,
                    show_id,
                    entered_order=a.entered_order,
                    new_song_id=a.song_id,
                    source="phishnet",
                    superseded_by=a.old_song_id,
                )
                overrides += 1
            if a.is_bustout:
                bustouts += 1

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        live.execute(
            "INSERT INTO live_show_meta (show_id, last_updated, last_error) "
            "VALUES (?, ?, NULL) "
            "ON CONFLICT(show_id) DO UPDATE SET "
            "last_updated=excluded.last_updated, last_error=NULL",
            (show_id, now),
        )
        live.commit()

    return {
        "status": "ok",
        "appended": appended,
        "overrides": overrides,
        "bustouts": bustouts,
        "last_updated": now,
    }
