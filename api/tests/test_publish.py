"""phishvs publish: the signing contract, the bundle shape, the seq log, the CLI.

The read DB here is seeded by hand (not the conftest fixture files) because a
bundle needs a candidate pool wide enough for 18 distinct picks plus a known
play history to pin the gap math against.
"""

import hashlib
import hmac
import json
import os
import shutil
import sys
from datetime import datetime, timedelta

import pytest
from pytest_httpx import HTTPXMock

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.inclusion import CALIBRATION_FILENAME, RUN_REPEAT_CHANCE
from phishpicker.model.scorer import HeuristicScorer
from phishpicker.publish import (
    build_bundle,
    next_bundle_seq,
    publish,
    record_publish,
    sign_headers,
)

# Matches conftest.seeded_live_show: a live show on 2026-04-23 at venue 1597.
SHOW_DATE = "2026-04-23"
VENUE_ID = 1597
TOUR_ID = 223

# Frozen vector shared with the phishvs (TypeScript) verifier. Do not change.
KNOWN_VECTOR_SIG = "89c6c3c39f3e649f2f5a991cb61838b6141c5b49c345be6e4424fa328ef55267"
# The same, over a body carrying the optional `model` block (also in phishvs).
MODEL_VECTOR_BODY = b'{"schema_version":1,"model":{"as_of":"2026-10-03"}}'
MODEL_VECTOR_SIG = "d7c184b58fbd7d63d7a561fb9af73137022e595341610ca7933788f733c34098"


def _seed_read_db(conn) -> None:
    conn.executescript(
        f"""
        INSERT INTO venues (venue_id, name, city, state, country) VALUES
            ({VENUE_ID}, 'Boardwalk Hall', 'Atlantic City', 'NJ', 'USA'),
            (1598, 'Elsewhere Arena', 'Denver', 'CO', 'USA');
        INSERT INTO tours (tour_id, name, start_date, end_date) VALUES
            ({TOUR_ID}, '2026 Spring Tour', '2026-04-10', '2026-04-30');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, fetched_at) VALUES
            (1, '2026-04-14', 1598, {TOUR_ID}, 'x'),
            (2, '2026-04-15', 1598, {TOUR_ID}, 'x'),
            (3, '2026-04-16', 1598, {TOUR_ID}, 'x'),
            (4, '2026-04-17', 1598, {TOUR_ID}, 'x'),
            (5, '2026-04-18', 1598, {TOUR_ID}, 'x'),
            (6, '{SHOW_DATE}', {VENUE_ID}, {TOUR_ID}, 'x'),
            (7, '2026-04-24', {VENUE_ID}, {TOUR_ID}, 'x'),
            (8, '2026-04-25', {VENUE_ID}, {TOUR_ID}, 'x');
        """
    )
    for sid in range(1, 21):
        conn.execute(
            "INSERT INTO songs (song_id, name, first_seen_at) VALUES (?, ?, 'x')",
            (sid, f"Song {sid}"),
        )
    conn.execute(
        "INSERT INTO songs (song_id, name, first_seen_at, is_bustout_placeholder) "
        "VALUES (99, 'Bustout placeholder', 'x', 1)"
    )
    # Song 1: last played 04-15 -> shows 04-16, 04-17, 04-18 lie strictly
    # between it and SHOW_DATE (gap 3). Song 20 is never played. Song 99 (the
    # placeholder) has a play but must never reach the catalog.
    setlists = {
        1: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        2: [1, 2, 3, 13, 14, 15],
        3: [2, 4, 16, 17],
        4: [3, 5, 18, 19],
        5: [6, 7, 8, 99],
    }
    for show_id, songs in setlists.items():
        conn.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (?, '1', ?, ?)",
            [(show_id, pos, sid) for pos, sid in enumerate(songs, start=1)],
        )
    conn.commit()


@pytest.fixture
def read_conn(tmp_path):
    conn = open_db(tmp_path / "phishpicker.db")
    apply_schema(conn)
    _seed_read_db(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def scorer():
    return HeuristicScorer()


def _verify(headers: dict[str, str], body: bytes, secret: str) -> bool:
    canon = (
        f"1\n{headers['X-Phishvs-Key-Id']}\n{headers['X-Phishvs-Timestamp']}\n"
        f"{headers['X-Phishvs-Nonce']}\n{hashlib.sha256(body).hexdigest()}"
    ).encode()
    expected = hmac.new(secret.encode(), canon, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Phishvs-Signature"])


# --- signing -----------------------------------------------------------------


def test_sign_headers_is_hmac_over_canonical_string():
    body = b'{"a":1}'
    h = sign_headers(body, key_id="k1", secret="s3cret", timestamp=1700000000, nonce="ab" * 16)
    canon = f"1\nk1\n1700000000\n{'ab' * 16}\n{hashlib.sha256(body).hexdigest()}".encode()
    assert h["X-Phishvs-Signature"] == hmac.new(b"s3cret", canon, hashlib.sha256).hexdigest()
    assert h["X-Phishvs-Key-Id"] == "k1" and h["X-Phishvs-Timestamp"] == "1700000000"
    assert h["X-Phishvs-Nonce"] == "ab" * 16
    assert h["Content-Type"] == "application/json"


def test_sign_headers_known_vector():
    body = b'{"schema_version":1}'
    h = sign_headers(
        body, key_id="test-key", secret="test-secret", timestamp=1760000000, nonce="00" * 16
    )
    assert h["X-Phishvs-Signature"] == KNOWN_VECTOR_SIG


def test_sign_headers_known_vector_with_model():
    h = sign_headers(
        MODEL_VECTOR_BODY,
        key_id="test-key",
        secret="test-secret",
        timestamp=1760000000,
        nonce="00" * 16,
    )
    assert h["X-Phishvs-Signature"] == MODEL_VECTOR_SIG


def test_sign_headers_defaults_to_now_and_random_nonce():
    a = sign_headers(b"x", key_id="k", secret="s")
    b = sign_headers(b"x", key_id="k", secret="s")
    assert a["X-Phishvs-Nonce"] != b["X-Phishvs-Nonce"]
    assert len(bytes.fromhex(a["X-Phishvs-Nonce"])) == 16
    assert int(a["X-Phishvs-Timestamp"]) > 1_700_000_000


# --- bundle ------------------------------------------------------------------


def test_build_bundle_shape(read_conn, live_conn, scorer, seeded_live_show):
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    assert b["schema_version"] == 1 and b["bundle_seq"] == 1
    assert [tuple(s) for s in b["structure"]] == [("1", 9), ("2", 7), ("E", 2)]
    assert len(b["picker_bracket"]) == 18
    assert b["slots"][0]["top_k"][0]["song_id"] == b["picker_bracket"][0]["song_id"]
    assert {"song_id", "name", "plays", "last_played", "gap", "placeholder"} <= set(b["catalog"][0])
    assert all(not c["placeholder"] for c in b["catalog"])
    assert len({p["song_id"] for p in b["picker_bracket"]}) == 18  # no dupes
    assert set(b["show"]) >= {
        "showid",
        "date",
        "venueid",
        "venue",
        "city",
        "state",
        "tz",
        "tourid",
        "tour_name",
        "run_position",
        "run_length",
    }


def test_build_bundle_show_meta(read_conn, live_conn, scorer, seeded_live_show):
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    assert b["show"] == {
        "showid": 6,
        "date": SHOW_DATE,
        "venueid": VENUE_ID,
        "venue": "Boardwalk Hall",
        "city": "Atlantic City",
        "state": "NJ",
        "tz": "America/New_York",
        "tourid": TOUR_ID,
        "tour_name": "2026 Spring Tour",
        "run_position": 1,
        "run_length": 3,
    }


def test_build_bundle_slots_and_bracket_agree(read_conn, live_conn, scorer, seeded_live_show):
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
        top_k=5,
    )
    assert [(s["set"], s["position"]) for s in b["slots"]] == [
        (p["set"], p["position"]) for p in b["picker_bracket"]
    ]
    for slot, pick in zip(b["slots"], b["picker_bracket"], strict=True):
        assert slot["top_k"][0]["song_id"] == pick["song_id"]
        assert [c["rank"] for c in slot["top_k"]] == list(range(1, len(slot["top_k"]) + 1))
        assert len(slot["top_k"]) <= 5
        assert all(0.0 < c["prob"] <= 1.0 for c in slot["top_k"])


def test_build_bundle_structure_follows_preview_slot_order(
    read_conn, live_conn, scorer, seeded_live_show
):
    live_conn.execute(
        "INSERT INTO live_show_meta (show_id, set1_size, set2_size, encore_size) "
        "VALUES (?, 3, 2, 1)",
        (seeded_live_show,),
    )
    live_conn.commit()
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    assert [tuple(s) for s in b["structure"]] == [("1", 3), ("2", 2), ("E", 1)]
    assert [(s["set"], s["position"]) for s in b["slots"]] == [
        ("1", 1),
        ("1", 2),
        ("1", 3),
        ("2", 1),
        ("2", 2),
        ("E", 1),
    ]


def test_build_bundle_catalog_gap_and_plays(read_conn, live_conn, scorer, seeded_live_show):
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    cat = {c["song_id"]: c for c in b["catalog"]}
    assert set(cat) == set(range(1, 21))  # 20 real songs, no placeholder
    assert cat[1] == {
        "song_id": 1,
        "name": "Song 1",
        "plays": 2,
        "last_played": "2026-04-15",
        "gap": 3,
        "placeholder": False,
    }
    assert cat[20]["plays"] == 0
    assert cat[20]["last_played"] is None and cat[20]["gap"] is None
    # Every candidate the model offers resolves in the catalog (fans auto-fill from it).
    assert {c["song_id"] for s in b["slots"] for c in s["top_k"]} <= set(cat)


def test_build_bundle_uses_frozen_bracket_when_present(
    read_conn, live_conn, scorer, seeded_live_show
):
    """picker_bracket is what phishpicker itself scores against — the frozen
    bracket — not a fresh top-1 rebuild, which can drift once ingest lands."""
    from phishpicker.scoring_store import upsert_score_state

    fresh = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    # A deliberately different bracket: the fresh top-1 picks in reverse slot order.
    reversed_ids = [p["song_id"] for p in reversed(fresh["picker_bracket"])]
    frozen = [
        {"set_number": p["set"], "position": p["position"], "song_id": sid}
        for p, sid in zip(fresh["picker_bracket"], reversed_ids, strict=True)
    ]
    assert [f["song_id"] for f in frozen] != [p["song_id"] for p in fresh["picker_bracket"]]
    upsert_score_state(live_conn, seeded_live_show, model_sha="x", frozen_bracket=frozen)

    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=2,
    )
    assert b["picker_bracket"] == [
        {"song_id": f["song_id"], "set": f["set_number"], "position": f["position"]} for f in frozen
    ]
    assert b["slots"] == fresh["slots"]  # top_k is still the live model view


def test_build_bundle_drops_placeholders_from_frozen_bracket(
    read_conn, live_conn, scorer, seeded_live_show
):
    from phishpicker.scoring_store import upsert_score_state

    frozen = [
        {"set_number": "1", "position": 1, "song_id": 99},  # the placeholder
        {"set_number": "1", "position": 2, "song_id": 3},
    ]
    upsert_score_state(live_conn, seeded_live_show, model_sha="x", frozen_bracket=frozen)
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=1,
    )
    assert b["picker_bracket"] == [{"song_id": 3, "set": "1", "position": 2}]


def test_build_bundle_is_json_serializable(read_conn, live_conn, scorer, seeded_live_show):
    b = build_bundle(
        read_conn=read_conn,
        live_conn=live_conn,
        show_id=seeded_live_show,
        scorer=scorer,
        bundle_seq=7,
    )
    assert json.loads(json.dumps(b, separators=(",", ":")))["bundle_seq"] == 7


# --- publish_log -------------------------------------------------------------


def test_bundle_seq_starts_at_one_and_increments(live_conn, seeded_live_show):
    assert next_bundle_seq(live_conn, seeded_live_show) == 1
    record_publish(live_conn, seeded_live_show, 1)
    assert next_bundle_seq(live_conn, seeded_live_show) == 2
    record_publish(live_conn, seeded_live_show, 2)
    assert next_bundle_seq(live_conn, seeded_live_show) == 3
    # Per show, not global.
    assert next_bundle_seq(live_conn, "some-other-show") == 1


# --- POST --------------------------------------------------------------------


def test_publish_posts_signed_body(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200, json={"ok": 1})
    bundle = {"schema_version": 1, "bundle_seq": 2, "slots": []}
    publish(bundle, url="https://phishvs.test/publish", key_id="k1", secret="s3cret")
    req = httpx_mock.get_request()
    assert req.method == "POST"
    assert req.headers["Content-Type"] == "application/json"
    assert req.content == json.dumps(bundle, separators=(",", ":")).encode()
    assert _verify(req.headers, req.content, "s3cret")


def test_publish_raises_on_non_2xx(httpx_mock: HTTPXMock):
    import httpx

    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=401)
    with pytest.raises(httpx.HTTPStatusError):
        publish({"schema_version": 1}, url="https://phishvs.test/publish", key_id="k", secret="s")


# --- CLI ---------------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch, tmp_path, read_conn):
    """Data dir with the seeded read DB + an empty live DB, and the env the CLI
    needs. The live show is created by the publish path itself."""
    from phishpicker.db.connection import apply_live_schema

    live = open_db(tmp_path / "live.db")
    apply_live_schema(live)
    live.close()
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHVS_PUBLISH_URL", "https://phishvs.test/publish")
    monkeypatch.setenv("PHISHVS_PUBLISH_KEY_ID", "k1")
    monkeypatch.setenv("PHISHVS_PUBLISH_SECRET", "s3cret")
    return tmp_path


def _run_cli(monkeypatch, *argv: str) -> int:
    import phishpicker.cli as cli

    monkeypatch.setattr(sys, "argv", ["phishpicker", *argv])
    return cli.main()


def test_cli_publish_posts_and_records_seq(cli_env, monkeypatch, httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    req = httpx_mock.get_request()
    assert _verify(req.headers, req.content, "s3cret")
    body = json.loads(req.content)
    assert body["bundle_seq"] == 1 and body["show"]["date"] == SHOW_DATE

    live = open_db(cli_env / "live.db")
    try:
        show_id = live.execute("SELECT show_id FROM live_show").fetchone()["show_id"]
        assert next_bundle_seq(live, show_id) == 2
    finally:
        live.close()
    assert "seq=1" in capsys.readouterr().out


def test_cli_publish_burns_seq_on_failed_post(cli_env, monkeypatch, httpx_mock: HTTPXMock, capsys):
    """The seq is reserved BEFORE the POST: a failed attempt leaves its row and
    the next attempt uses seq+1 — phishvs 409s a reused seq, which would stall
    the show forever."""
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=502)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 1
    assert "502" in capsys.readouterr().err
    live = open_db(cli_env / "live.db")
    try:
        assert [r[0] for r in live.execute("SELECT bundle_seq FROM publish_log")] == [1]
    finally:
        live.close()

    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    assert json.loads(httpx_mock.get_requests()[-1].content)["bundle_seq"] == 2


@pytest.fixture
def live_show_without_canonical_row(cli_env, monkeypatch):
    """A live show on a date with no `shows` row. The resolvers would refuse it,
    so stub them to hand the show back anyway — the guard under test is the one
    after resolution, which keeps a null showid off the wire."""
    from phishpicker import publish as mod
    from phishpicker.live import create_live_show

    live = open_db(cli_env / "live.db")
    show_id = create_live_show(live, "2026-04-20", venue_id=VENUE_ID)
    live.close()
    monkeypatch.setattr(mod, "freeze_show", lambda _s, _sc, _date: show_id)
    # The dry-run path resolves without freezing; both must hit the same guard.
    monkeypatch.setattr(mod, "resolve_live_show", lambda _s, _date: show_id)
    return show_id


def test_publish_show_skips_without_canonical_row(
    live_show_without_canonical_row, httpx_mock: HTTPXMock, caplog, cli_env
):
    """phishvs 400s a null showid, and the seq is reserved before the POST —
    so a missing canonical row must skip before either happens."""
    from phishpicker.config import Settings
    from phishpicker.publish import publish_show

    with caplog.at_level("WARNING", logger="phishpicker.publish"):
        result = publish_show(Settings(), HeuristicScorer(), "2026-04-20")
    assert result == {"skipped": "no_canonical_show"}
    assert httpx_mock.get_requests() == []
    assert "publish: no canonical show row for 2026-04-20; skipping" in caplog.text
    live = open_db(cli_env / "live.db")
    try:
        assert live.execute("SELECT COUNT(*) FROM publish_log").fetchone()[0] == 0
    finally:
        live.close()


@pytest.mark.parametrize("extra", [(), ("--dry-run",)])
def test_cli_publish_skip_without_canonical_row_exits_zero(
    live_show_without_canonical_row, monkeypatch, httpx_mock: HTTPXMock, capsys, extra
):
    assert _run_cli(monkeypatch, "publish", "--date", "2026-04-20", *extra) == 0
    assert httpx_mock.get_requests() == []
    assert "no canonical show row for 2026-04-20" in capsys.readouterr().out


def test_publish_tick_treats_skip_as_not_published(live_show_without_canonical_row, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from phishpicker import publish as mod
    from phishpicker.config import Settings

    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 4, 20, 12, 0, tzinfo=tz)
    state: dict = {}
    mod.mark_ingested(state, now)
    # publish_due's own canonical check would stop earlier; bypass it so the
    # tick reaches publish_show and sees the skip.
    monkeypatch.setattr(mod, "publish_due", lambda *_a, **_k: "2026-04-20")
    assert not mod.publish_tick(Settings(), HeuristicScorer, state, now)
    assert "last_published_at" not in state


def test_cli_publish_rejects_malformed_date(cli_env, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "publish", "--date", "tomorrow")
    assert exc.value.code == 2


def test_cli_publish_dry_run_does_not_post_or_record(
    cli_env, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE, "--dry-run") == 0
    assert httpx_mock.get_requests() == []
    out = capsys.readouterr().out
    assert "seq=1" in out and "slots=18" in out and "catalog=20" in out and "bytes=" in out
    live = open_db(cli_env / "live.db")
    try:
        assert live.execute("SELECT COUNT(*) FROM publish_log").fetchone()[0] == 0
    finally:
        live.close()


def test_cli_publish_dry_run_does_not_freeze_the_bracket(cli_env, monkeypatch, capsys):
    """Freezing is a deliberate one-shot: nothing refreshes it. A dry run that
    froze a future show would hand that night the bracket of whatever model was
    loaded the day someone checked — which is how 2026-10-02 came to be frozen
    three weeks early (docs/retros/2026-09-20-rehearsal.md)."""
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE, "--dry-run") == 0
    assert "slots=18" in capsys.readouterr().out

    live = open_db(cli_env / "live.db")
    try:
        frozen = live.execute(
            "SELECT frozen_bracket FROM live_score_state WHERE show_id IN "
            "(SELECT show_id FROM live_show WHERE show_date = ?)",
            (SHOW_DATE,),
        ).fetchall()
    finally:
        live.close()
    assert [r["frozen_bracket"] for r in frozen if r["frozen_bracket"]] == []


def test_cli_publish_for_real_still_freezes(cli_env, monkeypatch, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0

    live = open_db(cli_env / "live.db")
    try:
        row = live.execute(
            "SELECT frozen_bracket FROM live_score_state WHERE show_id IN "
            "(SELECT show_id FROM live_show WHERE show_date = ?)",
            (SHOW_DATE,),
        ).fetchone()
    finally:
        live.close()
    assert row is not None and row["frozen_bracket"]


def test_cli_publish_no_show_on_date_exits_nonzero(cli_env, monkeypatch, capsys):
    assert _run_cli(monkeypatch, "publish", "--date", "2026-04-20") != 0
    assert "no show on 2026-04-20" in capsys.readouterr().err


def test_cli_publish_unconfigured_is_noop(cli_env, monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("PHISHVS_PUBLISH_SECRET", "")
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    assert httpx_mock.get_requests() == []


# --- model stats (the About PhishPicker page) ---------------------------------

METRICS = {
    "trained_at": "2026-04-26T03:03:46+00:00",
    "cutoff_date": "2026-04-25",
    "n_shows_trained_on": 2250,
    "n_slots": 356,
    "holdout_shows": 20,
    "top1": 0.0646,
    "top5": 0.2022,
    "top20": 0.4185,
    "baselines": {"random": {"top1": 0.0, "top5": 0.0056, "top20": 0.0197, "mrr": 0.0075}},
    "feature_importance_gain": {"bigram_prev_to_this": 60.0, "era": 40.0},
}


def _seed_versus_scorecard(data_dir, show_date: str, picker: int, phish: int) -> None:
    from phishpicker.live import create_live_show

    live = open_db(data_dir / "live.db")
    try:
        show_id = create_live_show(live, show_date, venue_id=VENUE_ID)
        payload = {"versus": {"picker_total": picker, "phish_total": phish, "leader": "picker"}}
        live.execute(
            "INSERT INTO scorecards (show_id, show_date, finalized_at, combined, "
            "foresight_total, live_total, ppps, max_streak, payload) "
            "VALUES (?, ?, 'x', 0, 0, 0, 0, 0, ?)",
            (show_id, show_date, json.dumps(payload)),
        )
        live.commit()
    finally:
        live.close()


def _strict_json(content: bytes) -> dict:
    """Parse the way phishvs does (JSON.parse): NaN/Infinity are errors."""

    def reject(token: str):
        raise ValueError(f"non-standard JSON constant {token}")

    return json.loads(content, parse_constant=reject)


def test_cli_publish_carries_model_stats(cli_env, monkeypatch, httpx_mock: HTTPXMock):
    (cli_env / "metrics.json").write_text(json.dumps(METRICS))
    _seed_versus_scorecard(cli_env, "2026-04-18", 52, 35)
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0

    req = httpx_mock.get_request()
    assert _verify(req.headers, req.content, "s3cret")  # the signature covers `model` too
    body = _strict_json(req.content)
    assert body["model"] == {
        "as_of": "2026-04-18",
        "about": METRICS,
        "record": [{"date": "2026-04-18", "picker": 52, "phish": 35}],
        "signals": [
            {"feature": "bigram_prev_to_this", "share": 60.0},
            {"feature": "era", "share": 40.0},
        ],
    }
    # Everything else is the bundle as before.
    assert body["bundle_seq"] == 1 and len(body["picker_bracket"]) == 18


def test_cli_publish_without_metrics_omits_model(
    cli_env, monkeypatch, httpx_mock: HTTPXMock, caplog
):
    """No metrics.json (no training has shipped): the bundle goes out without
    `model` and phishvs keeps whatever it has."""
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    with caplog.at_level("WARNING", logger="phishpicker.publish"):
        assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    body = _strict_json(httpx_mock.get_request().content)
    assert "model" not in body and body["bundle_seq"] == 1
    assert "no metrics.json" in caplog.text


def test_publish_goes_out_without_model_when_the_stats_fail(
    cli_env, monkeypatch, httpx_mock: HTTPXMock, caplog
):
    """The stats are a passenger: if building them raises, the bundle still
    posts (and the failure is logged), never the other way round."""
    from phishpicker import publish as mod

    def boom(*_a, **_k):
        raise RuntimeError("scorecards unreadable")

    (cli_env / "metrics.json").write_text(json.dumps(METRICS))
    monkeypatch.setattr(mod, "model_stats", boom)
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    with caplog.at_level("ERROR", logger="phishpicker.publish"):
        assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    body = _strict_json(httpx_mock.get_request().content)
    assert "model" not in body and len(body["picker_bracket"]) == 18
    assert "model stats failed" in caplog.text and "scorecards unreadable" in caplog.text


def test_publish_drops_model_stats_that_are_not_strict_json(
    cli_env, monkeypatch, httpx_mock: HTTPXMock
):
    """Python writes NaN into JSON; JSON.parse rejects it, and phishvs would
    400 the whole body. A NaN in metrics.json must cost the stats, not the bundle."""
    (cli_env / "metrics.json").write_text(json.dumps({**METRICS, "top1": float("nan")}))
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    body = _strict_json(httpx_mock.get_request().content)
    assert "model" not in body and body["bundle_seq"] == 1


@pytest.mark.parametrize(("metrics", "flag"), [(METRICS, "model=yes"), (None, "model=no")])
def test_cli_publish_dry_run_says_whether_model_stats_ride_along(
    cli_env, monkeypatch, capsys, metrics, flag
):
    if metrics is not None:
        (cli_env / "metrics.json").write_text(json.dumps(metrics))
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE, "--dry-run") == 0
    assert flag in capsys.readouterr().out


# --- Likely Tonight chances (the bonus pick) -----------------------------------

# conftest.build_inclusion_runs_db: the first two nights of a 3-night run. Song 1
# plays every show, so by night 2 it has already been played this run.
RUN_NIGHT1, RUN_NIGHT2 = 5012, 5013
STAPLE = 1
INCLUSION_FILES = ("inclusion_model.lgb", "inclusion_model.meta.json")


@pytest.fixture(scope="module")
def inclusion_model(tmp_path_factory):
    """A Likely Tonight model (and its calibration) trained on conftest's
    multi-night-run DB; this module's publish DB is too small to train on.
    Serving needs only the feature columns to match, so it scores either DB."""
    from phishpicker.train.inclusion_runner import train_inclusion
    from tests.conftest import build_inclusion_runs_db

    d = tmp_path_factory.mktemp("inclusion")
    build_inclusion_runs_db(d / "phishpicker.db")
    model = d / "inclusion_model.lgb"
    train_inclusion(
        d / "phishpicker.db",
        model,
        holdout_days=30,
        num_boost_round=20,
        warmup_shows=3,
        block_shows=4,
    )
    return model


def _install_inclusion(model, data_dir, *, calibration: bool = False) -> None:
    names = INCLUSION_FILES + ((CALIBRATION_FILENAME,) if calibration else ())
    for name in names:
        shutil.copy(model.parent / name, data_dir / name)


@pytest.fixture
def runs_conn(inclusion_runs_db):
    conn = open_db(inclusion_runs_db)
    try:
        yield conn
    finally:
        conn.close()


def test_chances_block_prices_every_candidate_as_likely_tonight_does(
    inclusion_model, inclusion_runs_db, runs_conn
):
    """Every candidate, likeliest first, at the chance the NAS's Likely Tonight
    page shows (calibration included), so the bonus prices and the page agree."""
    from phishpicker import publish as mod
    from phishpicker.inclusion import (
        likely_tonight,
        load_inclusion_calibration,
        load_inclusion_scorer,
    )

    data = inclusion_runs_db.parent
    _install_inclusion(inclusion_model, data, calibration=True)
    block = mod._chances_block(runs_conn, RUN_NIGHT1, data)

    assert set(block) == {"as_of", "songs"}
    assert datetime.fromisoformat(block["as_of"]).utcoffset() == timedelta(0)
    assert len(block["as_of"]) <= 64
    model = data / "inclusion_model.lgb"
    cal = load_inclusion_calibration(data / CALIBRATION_FILENAME, model)
    assert cal is not None
    page = likely_tonight(
        runs_conn, RUN_NIGHT1, load_inclusion_scorer(model), top_n=1000, calibration=cal
    )
    assert [s["song_id"] for s in block["songs"]] == [r["song_id"] for r in page]
    for song, row in zip(block["songs"], page, strict=True):
        assert song["chance"] == pytest.approx(row["probability"], abs=1e-4)
    chances = [s["chance"] for s in block["songs"]]
    assert chances == sorted(chances, reverse=True)
    assert all(0 < c <= 1 and round(c, 5) == c for c in chances)


def test_chances_block_prices_a_song_played_earlier_in_the_run_at_the_repeat_chance(
    inclusion_model, inclusion_runs_db, runs_conn
):
    from phishpicker import publish as mod

    data = inclusion_runs_db.parent
    _install_inclusion(inclusion_model, data)
    night1, night2 = (
        {s["song_id"]: s["chance"] for s in mod._chances_block(runs_conn, n, data)["songs"]}
        for n in (RUN_NIGHT1, RUN_NIGHT2)
    )
    assert night1[STAPLE] > RUN_REPEAT_CHANCE
    assert night2[STAPLE] == RUN_REPEAT_CHANCE == 0.002


def test_chances_block_applies_the_calibration_only_when_it_matches_the_model(
    inclusion_model, inclusion_runs_db, runs_conn
):
    from phishpicker import publish as mod
    from phishpicker.inclusion import file_sha256

    data = inclusion_runs_db.parent
    _install_inclusion(inclusion_model, data)
    cal = data / CALIBRATION_FILENAME
    flat = {"x": [0.0, 1.0], "y": [0.25, 0.25]}
    cal.write_text(json.dumps({**flat, "model_sha256": file_sha256(data / "inclusion_model.lgb")}))
    block = mod._chances_block(runs_conn, RUN_NIGHT2, data)
    assert {s["chance"] for s in block["songs"]} == {0.25}

    # Fitted for another model: raw chances again (and the new file is picked up).
    cal.write_text(json.dumps({**flat, "model_sha256": "another-model"}))
    block = mod._chances_block(runs_conn, RUN_NIGHT2, data)
    assert {s["song_id"]: s["chance"] for s in block["songs"]}[STAPLE] == RUN_REPEAT_CHANCE


def test_chances_block_loads_the_model_once_until_its_files_change(
    inclusion_model, inclusion_runs_db, runs_conn, monkeypatch
):
    """The sidecar publishes hourly on a show day: load the model once, and
    again only when a retrain replaces it."""
    from phishpicker import publish as mod

    data = inclusion_runs_db.parent
    _install_inclusion(inclusion_model, data)
    loads = []
    real_load = mod.load_inclusion_scorer

    def counting_load(path):
        loads.append(path)
        return real_load(path)

    monkeypatch.setattr(mod, "load_inclusion_scorer", counting_load)
    first = mod._chances_block(runs_conn, RUN_NIGHT1, data)
    assert mod._chances_block(runs_conn, RUN_NIGHT1, data) is not None
    assert len(loads) == 1

    model = data / "inclusion_model.lgb"
    st = model.stat()
    os.utime(model, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert mod._chances_block(runs_conn, RUN_NIGHT1, data)["songs"] == first["songs"]
    assert len(loads) == 2


def test_chances_block_rounds_floors_and_drops_placeholders(
    inclusion_model, read_conn, tmp_path, monkeypatch
):
    """5 places, never 0 (phishvs needs a chance > 0 to price a pick), and no
    placeholder: the catalog can't name one."""
    from phishpicker import publish as mod

    _install_inclusion(inclusion_model, tmp_path)
    monkeypatch.setattr(
        mod,
        "inclusion_chances",
        lambda *_a, **_k: [(3, 0.4321987), (99, 0.2), (7, 0.0000004)],
    )
    block = mod._chances_block(read_conn, 6, tmp_path)
    assert block["songs"] == [{"song_id": 3, "chance": 0.4322}, {"song_id": 7, "chance": 1e-05}]


def test_chances_block_keeps_at_most_3000_songs(
    inclusion_model, read_conn, tmp_path, monkeypatch
):
    from phishpicker import publish as mod

    _install_inclusion(inclusion_model, tmp_path)
    monkeypatch.setattr(
        mod, "inclusion_chances", lambda *_a, **_k: [(i, 0.5) for i in range(1, 3502)]
    )
    songs = mod._chances_block(read_conn, 6, tmp_path)["songs"]
    # The likeliest 3000, placeholder (99) excluded.
    assert [s["song_id"] for s in songs] == [i for i in range(1, 3002) if i != 99]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1.5])
def test_chances_block_is_dropped_when_a_chance_is_not_a_probability(
    inclusion_model, read_conn, tmp_path, monkeypatch, bad
):
    """phishvs ignores a block with a chance outside (0, 1], and a NaN would
    400 the whole body: drop the block, keep the bundle."""
    from phishpicker import publish as mod

    _install_inclusion(inclusion_model, tmp_path)
    monkeypatch.setattr(mod, "inclusion_chances", lambda *_a, **_k: [(1, 0.5), (2, bad)])
    assert mod._chances_block(read_conn, 6, tmp_path) is None


def test_chances_block_is_none_for_a_show_with_no_chances(inclusion_model, read_conn, tmp_path):
    from phishpicker import publish as mod

    _install_inclusion(inclusion_model, tmp_path)
    assert mod._chances_block(read_conn, 999_999, tmp_path) is None


def test_cli_publish_carries_chances(
    cli_env, inclusion_model, read_conn, monkeypatch, httpx_mock: HTTPXMock
):
    from phishpicker.inclusion import inclusion_chances, load_inclusion_scorer

    _install_inclusion(inclusion_model, cli_env, calibration=True)
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0

    req = httpx_mock.get_request()
    assert _verify(req.headers, req.content, "s3cret")  # the signature covers `chances`
    body = _strict_json(req.content)
    ids = [s["song_id"] for s in body["chances"]["songs"]]
    assert ids and len(set(ids)) == len(ids)
    # The placeholder (song 99) is a model candidate, but never reaches phishvs.
    scorer = load_inclusion_scorer(cli_env / "inclusion_model.lgb")
    assert 99 in dict(inclusion_chances(read_conn, 6, scorer))
    assert set(ids) <= {c["song_id"] for c in body["catalog"]} and 99 not in ids
    assert body["bundle_seq"] == 1 and len(body["picker_bracket"]) == 18


def test_cli_publish_without_inclusion_model_omits_chances(
    cli_env, monkeypatch, httpx_mock: HTTPXMock, caplog
):
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    with caplog.at_level("WARNING", logger="phishpicker.publish"):
        assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    body = _strict_json(httpx_mock.get_request().content)
    assert "chances" not in body and body["bundle_seq"] == 1
    assert "no inclusion model" in caplog.text


def test_publish_goes_out_without_chances_when_scoring_fails(
    cli_env, inclusion_model, monkeypatch, httpx_mock: HTTPXMock, caplog
):
    from phishpicker import publish as mod

    def boom(*_a, **_k):
        raise RuntimeError("inclusion features unreadable")

    _install_inclusion(inclusion_model, cli_env)
    monkeypatch.setattr(mod, "inclusion_chances", boom)
    httpx_mock.add_response(url="https://phishvs.test/publish", status_code=200)
    with caplog.at_level("ERROR", logger="phishpicker.publish"):
        assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    body = _strict_json(httpx_mock.get_request().content)
    assert "chances" not in body and len(body["picker_bracket"]) == 18
    assert "chances failed" in caplog.text and "inclusion features unreadable" in caplog.text


@pytest.mark.parametrize(("installed", "flag"), [(True, "chances=yes"), (False, "chances=no")])
def test_cli_publish_dry_run_says_whether_chances_ride_along(
    cli_env, inclusion_model, monkeypatch, capsys, installed, flag
):
    from phishpicker.config import Settings
    from phishpicker.publish import publish_show

    if installed:
        _install_inclusion(inclusion_model, cli_env)
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE, "--dry-run") == 0
    assert flag in capsys.readouterr().out
    summary = publish_show(Settings(), HeuristicScorer(), SHOW_DATE, dry_run=True)
    assert summary["chances"] is installed


# --- the schedule (#24): the next few shows, so phishvs can show them between shows ---


def test_build_schedule_lists_the_next_shows_with_the_bundle_show_block(read_conn):
    from phishpicker.publish import build_schedule

    body = build_schedule(read_conn, today="2026-04-23", limit=2)
    assert body["schema_version"] == 1
    assert body["structure"] == [["1", 9], ["2", 7], ["E", 2]]
    assert [s["date"] for s in body["shows"]] == ["2026-04-23", "2026-04-24"]
    first = body["shows"][0]
    assert first["showid"] == 6
    assert first["venue"] == "Boardwalk Hall"
    assert first["city"] == "Atlantic City" and first["state"] == "NJ"
    assert first["tz"] == "America/New_York"
    assert first["tourid"] == TOUR_ID and first["tour_name"] == "2026 Spring Tour"
    json.dumps(body)


def test_build_schedule_skips_past_shows_and_is_empty_past_the_last(read_conn):
    from phishpicker.publish import build_schedule

    assert [s["date"] for s in build_schedule(read_conn, today="2026-04-25")["shows"]] == ["2026-04-25"]
    assert build_schedule(read_conn, today="2026-05-01")["shows"] == []


def test_schedule_url_sits_beside_the_bundle_route():
    from phishpicker.publish import schedule_url

    assert schedule_url("https://phishpicker.com/ingest/bundle") == "https://phishpicker.com/ingest/schedule"


def test_cli_publish_schedule_posts_signed(cli_env, monkeypatch, httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(url="https://phishvs.test/schedule", status_code=200, json={"ok": True})
    assert _run_cli(monkeypatch, "publish-schedule", "--today", "2026-04-24") == 0
    req = httpx_mock.get_request()
    assert _verify(req.headers, req.content, "s3cret")
    assert [s["date"] for s in json.loads(req.content)["shows"]] == ["2026-04-24", "2026-04-25"]
    assert "2 shows" in capsys.readouterr().out


def test_cli_publish_schedule_dry_run_does_not_post(cli_env, monkeypatch, httpx_mock: HTTPXMock, capsys):
    assert _run_cli(monkeypatch, "publish-schedule", "--today", "2026-04-24", "--dry-run") == 0
    assert httpx_mock.get_requests() == []
    assert "dry-run" in capsys.readouterr().out


def test_ingest_cron_sends_the_schedule_after_a_good_ingest(cli_env, monkeypatch):
    import phishpicker.ingest_cron as cron

    sent = []
    monkeypatch.setattr(cron, "_run_ingest", lambda: 0)
    monkeypatch.setattr(cron, "_daily_pass", lambda **kw: None)
    monkeypatch.setattr("phishpicker.publish.publish_schedule", lambda settings, today, **kw: sent.append(today) or {"shows": 0})
    cron._ingest_and_pass({}, datetime(2026, 4, 24, 15, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC")))
    assert sent == ["2026-04-24"]


def test_ingest_cron_skips_the_schedule_after_a_failed_ingest(cli_env, monkeypatch):
    import phishpicker.ingest_cron as cron

    sent = []
    monkeypatch.setattr(cron, "_run_ingest", lambda: 1)
    monkeypatch.setattr(cron, "_daily_pass", lambda **kw: None)
    monkeypatch.setattr("phishpicker.publish.publish_schedule", lambda settings, today, **kw: sent.append(today))
    cron._ingest_and_pass({}, datetime(2026, 4, 24, 15, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC")))
    assert sent == []


def test_ingest_cron_logs_a_failed_schedule_send_and_carries_on(cli_env, monkeypatch, caplog):
    import phishpicker.ingest_cron as cron

    def boom(settings, today, **kw):
        raise RuntimeError("phishvs down")

    monkeypatch.setattr(cron, "_run_ingest", lambda: 0)
    monkeypatch.setattr(cron, "_daily_pass", lambda **kw: None)
    monkeypatch.setattr("phishpicker.publish.publish_schedule", boom)
    cron._ingest_and_pass({}, datetime(2026, 4, 24, 15, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC")))
    assert "schedule publish failed" in caplog.text
    assert "phishvs down" in caplog.text
