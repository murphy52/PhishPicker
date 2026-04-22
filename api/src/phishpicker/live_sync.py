"""Reconcile user-entered live_songs with phish.net's canonical setlist.

Matches by (set_number, within-set-position). Position within a set is derived
from the order of occurrence in `user_rows` (which the caller must pass in
entered_order order). For `net_rows`, we trust phish.net's `position` field.
"""

from dataclasses import dataclass


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
