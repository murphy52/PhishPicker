"""Web Push subscription store + payload sender.

Subscriptions persist in the live DB (they're tied to a device + session
lifetime, not to training data). send_push is a thin wrapper over
pywebpush that auto-removes subscriptions the push service reports as
gone (HTTP 410) — typical when a user uninstalls the PWA.
"""

import json
import logging
import sqlite3
from datetime import UTC, datetime

from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)

# pywebpush defaults to ttl=0, which means "deliver this instant or discard".
# A phone that is locked, on a dead cell, or briefly offline then never sees
# the push at all — and the push service still answers 201, so nothing looks
# wrong from here. Four hours outlives a set break and a walk to the parking
# lot without stacking up next-day noise: a song notification is worthless by
# the following morning.
PUSH_TTL_SECONDS = 4 * 60 * 60


def save_subscription(
    conn: sqlite3.Connection,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> None:
    """Insert-or-replace a push subscription keyed on endpoint."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, subscribed_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET "
        "p256dh=excluded.p256dh, auth=excluded.auth, "
        "subscribed_at=excluded.subscribed_at",
        (endpoint, p256dh, auth, now),
    )
    conn.commit()


def delete_subscription(conn: sqlite3.Connection, endpoint: str) -> bool:
    cur = conn.execute(
        "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
    )
    conn.commit()
    return cur.rowcount > 0


def list_subscriptions(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions"
    ).fetchall()]


def send_push(
    conn: sqlite3.Connection,
    payload: dict,
    *,
    vapid_private_key: str,
    vapid_subject: str,
) -> dict:
    """Send payload to every stored subscription.

    Returns {"sent": n, "removed": m} — "removed" counts 404/410 responses,
    which mean the browser revoked the subscription (user uninstalled the
    PWA, disabled notifications, cleared site data). We prune those so we
    don't keep hammering dead endpoints.
    """
    if not vapid_private_key:
        log.info("push send skipped: VAPID_PRIVATE_KEY unset")
        return {"sent": 0, "removed": 0}
    subs = list_subscriptions(conn)
    body = json.dumps(payload)
    sent = 0
    removed = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=body,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_subject},
                ttl=PUSH_TTL_SECONDS,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                delete_subscription(conn, sub["endpoint"])
                removed += 1
            else:
                log.warning("push send failed for %s: %s", sub["endpoint"], e)
    return {"sent": sent, "removed": removed}
