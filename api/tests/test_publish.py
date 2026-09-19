"""phishvs publish: the signing contract, the bundle shape, the seq log, the CLI.

The read DB here is seeded by hand (not the conftest fixture files) because a
bundle needs a candidate pool wide enough for 18 distinct picks plus a known
play history to pin the gap math against.
"""

import hashlib
import hmac
import json
import sys

import pytest
from pytest_httpx import HTTPXMock

from phishpicker.db.connection import apply_schema, open_db
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


def test_cli_publish_no_show_on_date_exits_nonzero(cli_env, monkeypatch, capsys):
    assert _run_cli(monkeypatch, "publish", "--date", "2026-04-20") != 0
    assert "no show on 2026-04-20" in capsys.readouterr().err


def test_cli_publish_unconfigured_is_noop(cli_env, monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("PHISHVS_PUBLISH_SECRET", "")
    assert _run_cli(monkeypatch, "publish", "--date", SHOW_DATE) == 0
    assert httpx_mock.get_requests() == []
