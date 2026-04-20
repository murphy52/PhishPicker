"""Tests for the nightly smoke-test harness.

The harness pulls a show's setlist from phish.net, replays each slot against
the deployed scorer, and writes one JSONL record per show with the per-slot
actual-vs-predicted ranks. The main invariants covered here:

* empty setlist → exit 0, nothing written (idempotent no-op);
* exactly one JSON object per show;
* re-running a date without ``--overwrite`` does not double-write;
* each slot's ``top_k`` is at most K entries;
* rank of the actual next song is computed relative to all songs in the DB.
"""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.model.scorer import HeuristicScorer
from phishpicker.nightly_smoke import run_nightly_smoke
from phishpicker.phishnet.client import PhishNetClient


@pytest.fixture
def read_db(tmp_path) -> Iterator[sqlite3.Connection]:
    """Small fixture DB: 5 songs, a single prior show so history exists."""
    c = open_db(tmp_path / "phishpicker.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (100, 'Chalk Dust Torture', '2020-01-01'),
            (101, 'Tweezer', '2020-01-01'),
            (102, 'Free', '2020-01-01'),
            (103, 'Tilting', '2020-01-01'),
            (104, 'Wilson', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (999, 'Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at) VALUES
            (900, '2026-04-16', 999, '2026-04-16');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id, trans_mark) VALUES
            (900, '1', 1, 100, ','),
            (900, '1', 2, 101, ',');
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client() -> Iterator[PhishNetClient]:
    with PhishNetClient(api_key="test-key", base_url="https://api.phish.net/v5") as c:
        yield c


def _mock_setlist(httpx_mock: HTTPXMock, date: str, rows: list[dict]) -> None:
    httpx_mock.add_response(
        url=f"https://api.phish.net/v5/setlists/showdate/{date}.json?apikey=test-key",
        json={"error": False, "data": rows},
    )


def _sample_setlist(show_id: int, date: str, songs: list[tuple[str, int, int, str]]) -> list[dict]:
    """Build phish.net setlist rows. songs = [(set, position, songid, song_name), ...]."""
    out = []
    for set_number, position, songid, name in songs:
        out.append(
            {
                "showid": show_id,
                "showdate": date,
                "artist_name": "Phish",
                "artistid": 1,
                "venue": "Sphere",
                "venueid": 999,
                "set": set_number,
                "position": position,
                "songid": songid,
                "song": name,
                "trans_mark": ",",
            }
        )
    return out


def test_smoke_handles_empty_setlist(read_db, client, httpx_mock: HTTPXMock, tmp_path: Path):
    """No data yet → no record written, caller gets an explicit 'no setlist' result."""
    _mock_setlist(httpx_mock, "2026-04-17", [])

    output = tmp_path / "nightly-predictions.jsonl"
    result = run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=10,
    )

    assert result["status"] == "no-setlist"
    assert not output.exists() or output.read_text() == ""


def test_smoke_records_one_json_object_per_show(
    read_db, client, httpx_mock: HTTPXMock, tmp_path: Path
):
    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [
            ("1", 1, 102, "Free"),
            ("1", 2, 103, "Tilting"),
            ("1", 3, 104, "Wilson"),
        ],
    )
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    result = run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=5,
    )

    assert result["status"] == "ok"
    lines = [line for line in output.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["date"] == "2026-04-17"
    assert record["show_id"] == 1764702334
    assert record["venue"] == "Sphere"
    assert record["total_slots"] == 3
    assert len(record["slots"]) == 3
    assert record["scorer_name"] == "heuristic"


def test_smoke_is_idempotent_without_overwrite(
    read_db, client, httpx_mock: HTTPXMock, tmp_path: Path
):
    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [("1", 1, 102, "Free"), ("1", 2, 103, "Tilting")],
    )
    # pytest-httpx matches each registered response once by default; register twice
    # so the second call resolves against the second registration. pytest_httpx v0.30+
    # supports `is_reusable=True`; easier to just register twice.
    _mock_setlist(httpx_mock, "2026-04-17", rows)
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    scorer = HeuristicScorer()

    r1 = run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=scorer,
        date="2026-04-17",
        output_path=output,
        top_k=3,
    )
    r2 = run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=scorer,
        date="2026-04-17",
        output_path=output,
        top_k=3,
    )

    assert r1["status"] == "ok"
    assert r2["status"] == "skipped"

    lines = [line for line in output.read_text().splitlines() if line.strip()]
    assert len(lines) == 1


def test_smoke_overwrite_replaces_existing_record(
    read_db, client, httpx_mock: HTTPXMock, tmp_path: Path
):
    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [("1", 1, 102, "Free"), ("1", 2, 103, "Tilting")],
    )
    _mock_setlist(httpx_mock, "2026-04-17", rows)
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    # Prepopulate with an unrelated show so overwrite must preserve it.
    output.write_text(json.dumps({"show_id": 555, "date": "2026-04-16"}) + "\n")

    run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=3,
    )
    run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=3,
        overwrite=True,
    )

    lines = [line for line in output.read_text().splitlines() if line.strip()]
    # We expect: the preserved unrelated show + the (once) overwritten 1764702334.
    assert len(lines) == 2
    show_ids = {json.loads(line)["show_id"] for line in lines}
    assert show_ids == {555, 1764702334}


def test_smoke_top_k_shape(read_db, client, httpx_mock: HTTPXMock, tmp_path: Path):
    """top_k is a cap — DB has 5 songs total, top_k=3 → each slot has 3 entries."""
    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [("1", 1, 102, "Free"), ("1", 2, 103, "Tilting"), ("1", 3, 104, "Wilson")],
    )
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=3,
    )
    record = json.loads(output.read_text().splitlines()[0])
    for slot in record["slots"]:
        assert len(slot["top_k"]) == 3
        for idx, entry in enumerate(slot["top_k"], start=1):
            assert entry["rank"] == idx
            assert "song_id" in entry
            assert "name" in entry


def test_smoke_actual_rank_is_correct(read_db, client, httpx_mock: HTTPXMock, tmp_path: Path):
    """With a deterministic scorer, the actual song's rank should be reproducible.

    We stub the scorer to make song_id=103 (Tilting) rank #1 at every slot; the
    actual setlist opens with Free (id=102), so slot 1 must report actual_rank=2
    (Tilting #1, Free #2 under our stub). Slot 2's played_songs contains Free, and
    the actual next is Tilting (rank #1).
    """

    class FixedScorer:
        name = "fixed"

        def score_candidates(
            self,
            conn,
            show_date,
            venue_id,
            played_songs,
            current_set,
            candidate_song_ids,
            prev_trans_mark=",",
            prev_set_number=None,
        ):
            # Higher score for song_id=103, then 102, then others by id desc.
            priority = {103: 100.0, 102: 50.0, 104: 10.0, 101: 5.0, 100: 1.0}
            return [(sid, priority.get(sid, 0.0)) for sid in candidate_song_ids]

    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [("1", 1, 102, "Free"), ("1", 2, 103, "Tilting")],
    )
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=FixedScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=5,
    )
    record = json.loads(output.read_text().splitlines()[0])
    assert record["scorer_name"] == "fixed"
    slot1, slot2 = record["slots"]

    # Slot 1: Tilting is #1 in our stub, Free (actual) is #2.
    assert slot1["actual_song_id"] == 102
    assert slot1["actual_song"] == "Free"
    assert slot1["actual_rank"] == 2
    assert slot1["top_k"][0]["song_id"] == 103

    # Slot 2: Free was just played but we do NOT apply post-rules for smoke,
    # so Tilting remains #1 — the actual song Tilting is rank 1.
    assert slot2["actual_song_id"] == 103
    assert slot2["actual_rank"] == 1


def test_smoke_filters_non_phish_rows(read_db, client, httpx_mock: HTTPXMock, tmp_path: Path):
    """Defensive: if phish.net ever returns a non-Phish row for the endpoint,
    it must be filtered out before slot replay."""
    rows = _sample_setlist(
        1764702334,
        "2026-04-17",
        [("1", 1, 102, "Free")],
    )
    rows.append(
        {
            "showid": 999999,
            "showdate": "2026-04-17",
            "artist_name": "Trey Anastasio Band",
            "artistid": 2,
            "venue": "Sphere",
            "venueid": 999,
            "set": "1",
            "position": 1,
            "songid": 9999,
            "song": "Not A Phish Song",
            "trans_mark": ",",
        }
    )
    _mock_setlist(httpx_mock, "2026-04-17", rows)

    output = tmp_path / "nightly-predictions.jsonl"
    run_nightly_smoke(
        conn=read_db,
        client=client,
        scorer=HeuristicScorer(),
        date="2026-04-17",
        output_path=output,
        top_k=3,
    )
    record = json.loads(output.read_text().splitlines()[0])
    assert record["show_id"] == 1764702334
    assert record["total_slots"] == 1
