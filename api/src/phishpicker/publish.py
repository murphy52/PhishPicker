"""Publish a show bundle to phishvs. The cloud never calls us; we push.

phishvs (the public bracket game) needs tonight's show metadata, the bracket
structure, the model's per-slot top-k (fans auto-fill from these), the model's
own top-1 bracket, and a catalog snapshot with rarity stats. The NAS is not
reachable from the cloud, so phishpicker POSTs an HMAC-signed JSON bundle the
morning of a show and then hourly until lock (see ingest_cron).

Signature contract (mirrored by the phishvs verifier — do not deviate):
    canonical = f"{schema_version}\\n{key_id}\\n{timestamp}\\n{nonce}\\n{sha256(body).hexdigest()}"
    X-Phishvs-Signature = hex(HMAC-SHA256(secret, canonical))
where `body` is the exact bytes POSTed: json.dumps(bundle, separators=(",", ":")).

Signature test vector (shared with the phishvs verifier):
    body      b'{"schema_version":1}'
    key_id    "test-key"
    secret    "test-secret"
    timestamp 1760000000
    nonce     "00" * 16
    -> X-Phishvs-Signature
       89c6c3c39f3e649f2f5a991cb61838b6141c5b49c345be6e4424fa328ef55267
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from phishpicker.close_out import freeze_show, show_on
from phishpicker.config import Settings
from phishpicker.db.connection import open_db
from phishpicker.last_show import rollover_today
from phishpicker.live_preview import build_preview
from phishpicker.scoring_store import get_score_state
from phishpicker.show_meta import resolve_show_meta
from phishpicker.venue_tz import tz_for_state

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Fans' brackets lock at 19:30 venue-local (a 19:00 downbeat plus the usual
# late start). Nothing is published after lock — the last bundle stands.
DEFAULT_LOCK_LOCAL = "19:30"
PUBLISH_INTERVAL = timedelta(hours=1)
# On a show day with no successful ingest yet, the sidecar retries the ingest
# this often (a failed 11am ingest would otherwise cost the whole day).
INGEST_RETRY = timedelta(minutes=30)


def sign_headers(
    body: bytes,
    *,
    key_id: str,
    secret: str,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    ts = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or secrets.token_hex(16)
    canon = (
        f"{SCHEMA_VERSION}\n{key_id}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
    ).encode()
    sig = hmac.new(secret.encode(), canon, hashlib.sha256).hexdigest()
    return {
        "X-Phishvs-Key-Id": key_id,
        "X-Phishvs-Timestamp": str(ts),
        "X-Phishvs-Nonce": nonce,
        "X-Phishvs-Signature": sig,
        "Content-Type": "application/json",
    }


def _catalog(read_conn: sqlite3.Connection, show_date: str) -> list[dict]:
    """Every non-placeholder song, with plays/last_played strictly before
    `show_date` and gap = shows strictly between last_played and show_date.

    All of `songs`, not just songs with a play before show_date: the model's
    candidate pool is the whole table, so this is what guarantees every
    top_k song_id resolves to a name on the phishvs side. (In practice the
    table only holds songs that have been played — ingest derives it from
    setlists — so this is ~1000 rows either way.)
    """
    rows = read_conn.execute(
        """
        SELECT s.song_id, s.name,
               -- sh is NULL for plays on/after show_date, so counting it
               -- (not ss) keeps those out. DISTINCT: a sandwich is one play.
               COUNT(DISTINCT sh.show_id) AS plays,
               MAX(sh.show_date) AS last_played
        FROM songs s
        LEFT JOIN setlist_songs ss ON ss.song_id = s.song_id
        LEFT JOIN shows sh ON sh.show_id = ss.show_id AND sh.show_date < ?
        WHERE s.is_bustout_placeholder = 0
        GROUP BY s.song_id
        ORDER BY s.song_id
        """,
        (show_date,),
    ).fetchall()
    # One COUNT per distinct last-played date, not per song — the same
    # memoization as scoring_service._surprise_weights.
    gap_by_date: dict[str, int] = {}
    catalog = []
    for r in rows:
        last = r["last_played"]
        gap: int | None = None
        if last is not None:
            if last not in gap_by_date:
                gap_by_date[last] = read_conn.execute(
                    "SELECT COUNT(*) FROM shows WHERE show_date > ? AND show_date < ?",
                    (last, show_date),
                ).fetchone()[0]
            gap = gap_by_date[last]
        catalog.append(
            {
                "song_id": r["song_id"],
                "name": r["name"],
                "plays": r["plays"],
                "last_played": last,
                "gap": gap,
                "placeholder": False,
            }
        )
    return catalog


def _show_block(read_conn: sqlite3.Connection, show_date: str, venue_id: int | None) -> dict:
    """Show metadata. The canonical `shows` row may not exist yet for a future
    date; then the ids/tour degrade to None and the rest comes from the venue."""
    meta = resolve_show_meta(read_conn, show_date, venue_id)
    canon = read_conn.execute(
        "SELECT s.show_id, s.venue_id, s.tour_id, t.name AS tour_name "
        "FROM shows s LEFT JOIN tours t ON t.tour_id = s.tour_id "
        "WHERE s.show_date = ? LIMIT 1",
        (show_date,),
    ).fetchone()
    if venue_id is None and canon:
        venue_id = canon["venue_id"]
    return {
        "showid": canon["show_id"] if canon else None,
        "date": show_date,
        "venueid": venue_id,
        "venue": meta["venue"],
        "city": meta["city"],
        "state": meta["state"],
        "tz": tz_for_state(meta["state"]),
        "tourid": canon["tour_id"] if canon else None,
        "tour_name": canon["tour_name"] if canon else None,
        "run_position": meta["run_position"],
        "run_length": meta["run_length"],
    }


def build_bundle(
    *,
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    show_id: str,
    scorer,
    bundle_seq: int,
    top_k: int = 8,
) -> dict:
    preview = build_preview(
        read_conn=read_conn, live_conn=live_conn, show_id=show_id, top_k=top_k, scorer=scorer
    )
    show = live_conn.execute(
        "SELECT show_date, venue_id FROM live_show WHERE show_id = ?", (show_id,)
    ).fetchone()
    show_date = show["show_date"]
    # The model's candidate pool is the whole songs table, placeholders
    # included (a stand-in row for a song phish.net hadn't listed yet). The
    # catalog excludes them, and a candidate the catalog can't name is useless
    # to phishvs, so drop them here and re-rank the remainder.
    placeholders = {
        r["song_id"]
        for r in read_conn.execute(
            "SELECT song_id FROM songs WHERE is_bustout_placeholder = 1"
        ).fetchall()
    }

    slots = []
    picker_bracket = []
    structure: dict[str, int] = {}
    for s in preview["slots"]:
        if s["state"] != "predicted":
            continue
        set_number, position = s["set_number"], s["position"]
        structure[set_number] = structure.get(set_number, 0) + 1
        cands = [c for c in s["top_k"] if c["song_id"] not in placeholders]
        slots.append(
            {
                "set": set_number,
                "position": position,
                "top_k": [
                    {"song_id": c["song_id"], "prob": c["probability"], "rank": i}
                    for i, c in enumerate(cands, start=1)
                ],
            }
        )
        if cands:
            picker_bracket.append(
                {"song_id": cands[0]["song_id"], "set": set_number, "position": position}
            )

    # picker_bracket is the bracket phishpicker itself scores against: the one
    # frozen in live_score_state (freeze_show runs before every publish). The
    # top-1 rebuild above is only the fallback for a show nothing has frozen.
    state = get_score_state(live_conn, show_id)
    if state and state["frozen_bracket"]:
        picker_bracket = [
            {"song_id": f["song_id"], "set": f["set_number"], "position": f["position"]}
            for f in state["frozen_bracket"]
            if f["song_id"] not in placeholders
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_seq": bundle_seq,
        "show": _show_block(read_conn, show_date, show["venue_id"]),
        "structure": [[k, n] for k, n in structure.items()],
        "picker_bracket": picker_bracket,
        "slots": slots,
        "catalog": _catalog(read_conn, show_date),
    }


def publish(bundle: dict, *, url: str, key_id: str, secret: str) -> httpx.Response:
    body = json.dumps(bundle, separators=(",", ":")).encode()
    resp = httpx.post(
        url, content=body, headers=sign_headers(body, key_id=key_id, secret=secret), timeout=30
    )
    resp.raise_for_status()
    return resp


# --- bundle_seq persistence ---------------------------------------------------


def next_bundle_seq(live_conn: sqlite3.Connection, show_id: str) -> int:
    row = live_conn.execute(
        "SELECT MAX(bundle_seq) FROM publish_log WHERE show_id = ?", (show_id,)
    ).fetchone()
    return (row[0] or 0) + 1


def record_publish(live_conn: sqlite3.Connection, show_id: str, seq: int) -> None:
    """Reserve `seq` for this show. Called BEFORE the POST, not after: phishvs
    rejects a seq at or below the one it already holds, so if a POST that
    actually landed (say, a timeout after the write) were retried with the
    same seq it would 409 forever. A burned seq on a failed POST is harmless."""
    live_conn.execute(
        "INSERT INTO publish_log (show_id, bundle_seq, published_at) VALUES (?, ?, ?)",
        (show_id, seq, datetime.now(UTC).isoformat()),
    )
    live_conn.commit()


# --- orchestration (CLI + cron) ----------------------------------------------


def configured(settings: Settings) -> bool:
    """False when any of the three phishvs settings is empty — publish is then
    a no-op, mirroring the VAPID convention. Callers log; this is a predicate."""
    return bool(
        settings.phishvs_publish_url
        and settings.phishvs_publish_key_id
        and settings.phishvs_publish_secret
    )


def publish_show(
    settings: Settings, scorer, show_date: str, *, dry_run: bool = False
) -> dict | None:
    """Build tonight's bundle, reserve its seq, POST it.

    Resolves the live show the same way the cron's daily pass does
    (close_out.freeze_show: canonical show on the date -> idempotent live_show
    row, bracket frozen). Returns None when there is no show on `show_date`;
    otherwise a summary dict {seq, slots, catalog, bytes}.
    """
    show_id = freeze_show(settings, scorer, show_date)
    if show_id is None:
        return None
    with (
        closing(open_db(settings.db_path, read_only=True)) as read,
        closing(open_db(settings.live_db_path)) as live,
    ):
        seq = next_bundle_seq(live, show_id)
        bundle = build_bundle(
            read_conn=read, live_conn=live, show_id=show_id, scorer=scorer, bundle_seq=seq
        )
        summary = {
            "seq": seq,
            "slots": len(bundle["slots"]),
            "catalog": len(bundle["catalog"]),
            "bytes": len(json.dumps(bundle, separators=(",", ":")).encode()),
        }
        if dry_run:
            return summary
        record_publish(live, show_id, seq)
    publish(
        bundle,
        url=settings.phishvs_publish_url,
        key_id=settings.phishvs_publish_key_id,
        secret=settings.phishvs_publish_secret,
    )
    log.info("publish: %s seq=%d (%d bytes)", show_date, seq, summary["bytes"])
    return summary


def lock_at(show_date: str, tz: ZoneInfo, lock_local: str = DEFAULT_LOCK_LOCAL) -> datetime:
    hour, minute = (int(p) for p in lock_local.split(":"))
    return datetime.fromisoformat(show_date).replace(hour=hour, minute=minute, tzinfo=tz)


def mark_ingested(state: dict, now: datetime) -> None:
    """Record that the daily ingest completed for the current rollover date.

    publish_tick refuses to publish (or freeze) until this matches today: the
    bracket must be built AFTER last night's setlist has landed, or on night
    2+ of a run the model loses run-awareness (no-repeat filter, run stats).
    Clearing the last-publish time makes the next tick publish at once.
    """
    state["ingested_date"] = rollover_today(now.astimezone(UTC))
    state.pop("last_published_at", None)


def _show_today(settings: Settings, today: str) -> dict | None:
    with closing(open_db(settings.db_path, read_only=True)) as read:
        return show_on(read, today)


def _today(now: datetime) -> str:
    # rollover_today does wall-clock arithmetic, so hand it UTC as app.py does.
    return rollover_today(now.astimezone(UTC))


def ingest_retry_due(settings: Settings, state: dict, now: datetime) -> bool:
    """True on a show day when today's ingest hasn't succeeded and the last
    attempt (if any) is at least INGEST_RETRY old. Never on a non-show day —
    there is nothing to publish, so the 11am schedule is enough."""
    today = _today(now)
    if state.get("ingested_date") == today:
        return False
    last = state.get("last_ingest_attempt_at")
    if last is not None and now - last < INGEST_RETRY:
        return False
    return _show_today(settings, today) is not None


def publish_due(
    settings: Settings, state: dict, now: datetime, *, lock_local: str = DEFAULT_LOCK_LOCAL
) -> str | None:
    """Today's date when a bundle should go out now, else None. Cheap gates
    only (no model load): configured, a show today, today's ingest done,
    before lock, and at least PUBLISH_INTERVAL since the last publish."""
    if not configured(settings):
        return None
    today = _today(now)
    show = _show_today(settings, today)
    if show is None:
        return None
    if state.get("ingested_date") != today:
        if state.get("held_date") != today:
            log.warning("publish: show on %s but no successful ingest yet; holding", today)
            state["held_date"] = today
        return None
    if now >= lock_at(today, show["tz"], lock_local):
        return None
    last = state.get("last_published_at")
    if last is not None and now - last < PUBLISH_INTERVAL:
        return None
    return today


def publish_tick(
    settings: Settings,
    load_scorer,
    state: dict,
    now: datetime,
    *,
    lock_local: str = DEFAULT_LOCK_LOCAL,
) -> bool:
    """One sidecar tick: publish today's show when publish_due says so.
    `load_scorer` is a zero-arg callable, invoked only when a bundle actually
    goes out. `state` is in-process: a fresh sidecar counts as not-yet-ingested
    until its own startup ingest marks it. A failed publish is logged and the
    hourly clock is left alone so the next tick retries. Returns True when a
    bundle was sent.
    """
    today = publish_due(settings, state, now, lock_local=lock_local)
    if today is None:
        return False
    try:
        publish_show(settings, load_scorer(), today)
    except Exception:
        log.exception("publish: failed for %s", today)
        return False
    state["last_published_at"] = now
    return True
