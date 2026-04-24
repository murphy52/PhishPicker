"""Reconcile user-entered live_songs with phish.net's canonical setlist.

Matches by (set_number, within-set-position). Position within a set is derived
from the order of occurrence in `user_rows` (which the caller must pass in
entered_order order). For `net_rows`, we trust phish.net's `position` field.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.live import append_song, get_live_show, replace_song_at
from phishpicker.phishnet.client import PhishNetClient
from phishpicker.predict import predict_next_stateless
from phishpicker.push import send_push

log = logging.getLogger(__name__)


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


def _rank_emoji(rank: int | None) -> str:
    if rank is None:
        return "🚨"
    if rank <= 3:
        return "🎯"
    if rank <= 10:
        return "🎵"
    if rank <= 20:
        return "🔍"
    return "🚨"


def _set_label(set_number: str) -> str:
    return "Encore" if set_number == "E" else f"Set {set_number}"


def sync_show_with_phishnet(
    *,
    db_path: Path,
    live_db_path: Path,
    api_key: str,
    show_id: str,
    show_date: str,
    scorer=None,
    vapid_private_key: str = "",
    vapid_subject: str = "",
) -> dict:
    """Idempotent reconcile of live_songs with phish.net's current setlist.

    Opens its OWN connections each call — this function is safe to call
    from an asyncio worker thread; do NOT pass connections in.

    When scorer + vapid_private_key are supplied, for each newly-appended
    song this also computes the model's rank for that slot at append time
    and fires a Web Push with the rank — the live scoreboard.
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
                "trans_mark": s["trans_mark"],
            }
            for s in live_show["songs"]
        ]
        actions = reconcile(user_rows, net_rows)

        # Running simulation of played state as we walk through appends, so
        # each rank lookup sees only what the model "knew" at that slot.
        virtual_played = [r["song_id"] for r in user_rows]
        last_set: str | None = user_rows[-1]["set_number"] if user_rows else None
        last_trans_mark = user_rows[-1]["trans_mark"] if user_rows else ","
        venue_id = live_show["venue_id"]
        do_rank = scorer is not None
        pending_pushes: list[dict] = []

        appended = overrides = bustouts = 0
        for a in actions:
            if a.kind == "append":
                rank: int | None = None
                prob: float | None = None
                name: str = ""
                if do_rank:
                    try:
                        cands = predict_next_stateless(
                            read_conn=read_rw,
                            played_songs=virtual_played,
                            current_set=a.set_number,
                            show_date=show_date,
                            venue_id=venue_id,
                            prev_trans_mark=last_trans_mark,
                            prev_set_number=last_set,
                            top_n=1000,
                            scorer=scorer,
                        )
                        for i, c in enumerate(cands):
                            if c["song_id"] == a.song_id:
                                rank = i + 1
                                prob = c["probability"]
                                name = c["name"]
                                break
                    except Exception as e:
                        log.warning("rank lookup failed for %s: %s", a.song_id, e)
                if not name:
                    row = read_rw.execute(
                        "SELECT name FROM songs WHERE song_id = ?", (a.song_id,)
                    ).fetchone()
                    name = row["name"] if row else f"#{a.song_id}"

                append_song(live, show_id, a.song_id, a.set_number, source="phishnet")
                appended += 1
                virtual_played = virtual_played + [a.song_id]
                last_set = a.set_number
                last_trans_mark = ","

                if vapid_private_key:
                    rank_str = (
                        f"#{rank}" + (f" ({prob * 100:.0f}%)" if prob else "")
                        if rank is not None
                        else "unranked"
                    )
                    pending_pushes.append(
                        {
                            "title": f"{_rank_emoji(rank)} {name}",
                            "body": (
                                f"{_set_label(a.set_number)} · "
                                f"Slot {a.position_in_set} · Model rank {rank_str}"
                            ),
                            "tag": f"phishpicker-{show_date}-{a.song_id}-{a.set_number}-{a.position_in_set}",
                            "data": {"url": "/"},
                        }
                    )
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

        # Mark user-entered songs that match phish.net's setlist as reconciled.
        # `reconcile()` skips these (no placement action needed), but once the
        # net confirms them they should no longer appear in the "undoable"
        # area — the frontend filters on source != 'user' for that.
        user_rows_by_key = _index_by_set_position(user_rows, position_source="user")
        net_rows_by_key = _index_by_set_position(net_rows, position_source="net")
        for (set_number, pos), user in user_rows_by_key.items():
            net = net_rows_by_key.get((set_number, pos))
            if net is not None and net["song_id"] == user["song_id"]:
                live.execute(
                    "UPDATE live_songs SET source = 'phishnet' "
                    "WHERE show_id = ? AND entered_order = ? AND source = 'user'",
                    (show_id, user["entered_order"]),
                )

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        live.execute(
            "INSERT INTO live_show_meta (show_id, last_updated, last_error) "
            "VALUES (?, ?, NULL) "
            "ON CONFLICT(show_id) DO UPDATE SET "
            "last_updated=excluded.last_updated, last_error=NULL",
            (show_id, now),
        )
        live.commit()

        for payload in pending_pushes:
            send_push(
                live,
                payload,
                vapid_private_key=vapid_private_key,
                vapid_subject=vapid_subject,
            )

    return {
        "status": "ok",
        "appended": appended,
        "overrides": overrides,
        "bustouts": bustouts,
        "last_updated": now,
    }


async def _default_sync(
    *,
    show_id,
    show_date,
    db_path,
    live_db_path,
    api_key,
    scorer=None,
    vapid_private_key: str = "",
    vapid_subject: str = "",
):
    await asyncio.to_thread(
        sync_show_with_phishnet,
        db_path=db_path,
        live_db_path=live_db_path,
        api_key=api_key,
        show_id=show_id,
        show_date=show_date,
        scorer=scorer,
        vapid_private_key=vapid_private_key,
        vapid_subject=vapid_subject,
    )


class PollerRegistry:
    """Per-show async poller. Tasks live on app.state so they're scoped to
    the FastAPI app lifecycle (not a module global). Each tick of a poller
    runs `sync_fn` with the show's kwargs; errors are caught and stored in
    `_meta[show_id]['last_error']` for /sync/status."""

    def __init__(self, sync_fn: Callable | None = None):
        self._tasks: dict[str, asyncio.Task] = {}
        self._meta: dict[str, dict] = {}
        self._sync_fn = sync_fn or _default_sync

    async def start(
        self,
        show_id: str,
        show_date: str,
        interval: float = 60.0,
        **sync_kwargs,
    ) -> None:
        if show_id in self._tasks and not self._tasks[show_id].done():
            return
        self._tasks[show_id] = asyncio.create_task(
            self._loop(show_id, show_date, interval, sync_kwargs)
        )

    async def stop(self, show_id: str) -> None:
        """Cancel the task AND await it so any in-flight asyncio.to_thread
        work completes (or its cancellation propagates) before returning.
        Prevents races where a cancelled task still writes to a closing DB."""
        task = self._tasks.pop(show_id, None)
        if not task or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def stop_all(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def last_error(self, show_id: str) -> str | None:
        return self._meta.get(show_id, {}).get("last_error")

    async def _loop(
        self, show_id: str, show_date: str, interval: float, sync_kwargs: dict
    ) -> None:
        while True:
            try:
                await self._sync_fn(
                    show_id=show_id, show_date=show_date, **sync_kwargs
                )
                self._meta.setdefault(show_id, {})["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("sync failed for %s: %s", show_id, e)
                self._meta.setdefault(show_id, {})["last_error"] = str(e)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
