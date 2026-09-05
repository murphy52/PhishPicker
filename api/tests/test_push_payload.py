"""Notification payload composition.

The push is the only surface David sees during a show without opening the
app, so its content is the product. build_song_push is pure so the wording
can be iterated (and reviewed) without a show running — see POST /push/test
for firing one at a real device.
"""

from phishpicker.push_payload import ICON_BUSTOUT, ICON_MISS, ICON_SCORED, build_song_push


def _payload(**over):
    base = {
        "song_name": "Tube",
        "set_number": "1",
        "position_in_set": 5,
        "show_date": "2026-09-05",
        "song_id": 622,
        "rank": 2,
        "probability": 0.18,
        "attribution": {"reason": "exact", "final": 80, "ledger": "foresight"},
        "versus": {"picker_total": 86, "phish_total": 40, "leader": "picker"},
    }
    base.update(over)
    return build_song_push(**base)


def test_title_is_the_song_name():
    """Song title leads — it's the one thing readable on a locked screen."""
    p = _payload()
    assert "Tube" in p["title"]


def test_body_carries_set_slot_points_accuracy_and_versus():
    body = _payload()["body"]
    assert "Set 1" in body
    assert "Slot 5" in body
    assert "+80" in body  # points scored
    assert "exact" in body.lower()  # how accurate the bracket was
    assert "#2" in body and "18%" in body  # next-song call + confidence
    assert "40" in body and "86" in body  # running Phish vs Picker


def test_encore_is_labelled_not_numbered():
    assert "Encore" in _payload(set_number="E")["body"]


def test_scored_song_uses_the_scored_icon():
    assert _payload()["icon"] == ICON_SCORED


def test_missed_song_uses_the_miss_icon():
    p = _payload(attribution={"reason": "absent", "final": 0, "ledger": None})
    assert p["icon"] == ICON_MISS
    assert "+" not in p["body"].split("\n")[0]  # no phantom "+0"


def test_bustout_gets_its_own_icon_and_call_out():
    p = _payload(attribution={"reason": "absent", "final": 0, "bustout": True})
    assert p["icon"] == ICON_BUSTOUT
    assert "Bustout" in p["body"]


def test_unranked_call_is_stated_not_blank():
    """A song outside the model's candidate list must say so — a missing
    rank line reads as a rendering bug, not as 'we never saw it coming'."""
    body = _payload(rank=None, probability=None)["body"]
    assert "unranked" in body.lower()


def test_versus_omitted_when_unavailable():
    """Scoring can fail without costing the notification — degrade, never raise."""
    p = _payload(versus=None)
    assert "Tube" in p["title"]
    assert "—" not in p["body"].split("\n")[-1] or "Phish" not in p["body"]


def test_tag_is_slot_unique_so_a_correction_replaces_not_stacks():
    a = _payload()["tag"]
    b = _payload(position_in_set=6)["tag"]
    assert a != b
    assert _payload()["tag"] == a  # stable for the same slot


def test_icon_can_be_overridden_for_device_probing():
    """iOS may ignore per-notification icons entirely; the override lets us
    fire a visually unmistakable one and find out."""
    assert _payload(icon="/globe.svg")["icon"] == "/globe.svg"


def test_push_test_endpoint_requires_admin_token(seeded_client):
    r = seeded_client.post("/push/test", json={})
    assert r.status_code == 401


def test_push_test_endpoint_rejects_wrong_token(seeded_client):
    r = seeded_client.post(
        "/push/test", json={}, headers={"X-Admin-Token": "nope"}
    )
    assert r.status_code == 401


def test_push_test_dry_run_composes_without_sending(seeded_client):
    r = seeded_client.post(
        "/push/test",
        json={"dry_run": True, "song_name": "Llama"},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sent"] == 0 and b["dry_run"] is True
    assert "Llama" in b["payload"]["title"]
    assert "Phish" in b["payload"]["body"]


def test_push_test_accepts_icon_override(seeded_client):
    r = seeded_client.post(
        "/push/test",
        json={"dry_run": True, "icon": "/globe.svg"},
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert r.json()["payload"]["icon"] == "/globe.svg"
