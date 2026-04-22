import sqlite3
from unittest.mock import patch

from phishpicker.db.connection import apply_live_schema
from phishpicker.push import (
    delete_subscription,
    list_subscriptions,
    save_subscription,
    send_push,
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    apply_live_schema(c)
    return c


def test_save_is_upsert():
    c = _conn()
    save_subscription(c, "https://push/abc", "p1", "a1")
    save_subscription(c, "https://push/abc", "p2", "a2")
    rows = list_subscriptions(c)
    assert len(rows) == 1
    assert rows[0]["p256dh"] == "p2"
    assert rows[0]["auth"] == "a2"


def test_delete_is_idempotent():
    c = _conn()
    save_subscription(c, "e1", "p", "a")
    assert delete_subscription(c, "e1") is True
    assert delete_subscription(c, "e1") is False


def test_send_push_skipped_without_vapid_key():
    c = _conn()
    save_subscription(c, "e1", "p", "a")
    result = send_push(
        c, {"title": "t"}, vapid_private_key="", vapid_subject="mailto:x"
    )
    assert result == {"sent": 0, "removed": 0}


def test_send_push_prunes_410_endpoints():
    c = _conn()
    save_subscription(c, "gone", "p", "a")
    save_subscription(c, "live", "p", "a")

    from pywebpush import WebPushException

    class FakeResp:
        def __init__(self, status: int):
            self.status_code = status

    def fake_webpush(*, subscription_info, **_):
        if subscription_info["endpoint"] == "gone":
            err = WebPushException("410 Gone")
            err.response = FakeResp(410)
            raise err

    with patch("phishpicker.push.webpush", side_effect=fake_webpush):
        result = send_push(
            c,
            {"title": "t"},
            vapid_private_key="fake-key",
            vapid_subject="mailto:x@y.z",
        )
    assert result == {"sent": 1, "removed": 1}
    assert [r["endpoint"] for r in list_subscriptions(c)] == ["live"]


def test_post_push_subscribe_persists(seeded_client):
    r = seeded_client.post(
        "/push/subscribe",
        json={
            "endpoint": "https://push.example/abc",
            "keys": {"p256dh": "pub", "auth": "secret"},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # Subscribing the same endpoint again is an upsert.
    r2 = seeded_client.post(
        "/push/subscribe",
        json={
            "endpoint": "https://push.example/abc",
            "keys": {"p256dh": "pub2", "auth": "secret2"},
        },
    )
    assert r2.status_code == 200


def test_post_push_subscribe_rejects_missing_keys(seeded_client):
    r = seeded_client.post(
        "/push/subscribe",
        json={"endpoint": "x", "keys": {"p256dh": "only"}},
    )
    assert r.status_code == 400


def test_delete_push_unsubscribe(seeded_client):
    seeded_client.post(
        "/push/subscribe",
        json={
            "endpoint": "https://push.example/x",
            "keys": {"p256dh": "p", "auth": "a"},
        },
    )
    r = seeded_client.request(
        "DELETE",
        "/push/subscribe",
        json={"endpoint": "https://push.example/x"},
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": True}


def test_get_vapid_key(seeded_client):
    r = seeded_client.get("/push/vapid-key")
    assert r.status_code == 200
    # tests don't set VAPID_PUBLIC_KEY, so expect empty string.
    assert "key" in r.json()
