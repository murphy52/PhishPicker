"""Tests for the show-level 'Likely Tonight' inclusion model."""

from pathlib import Path

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.inclusion import likely_tonight, load_inclusion_scorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    InclusionHistory,
)
from phishpicker.train.inclusion_runner import train_inclusion


def _build_db(path: Path):
    c = open_db(path)
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO tours (tour_id, name) VALUES (1, 'Test Tour');
        INSERT INTO songs (song_id, name, first_seen_at, debut_date, original_artist) VALUES
            (1, 'Staple',   '2019-01-01', '2019-01-01', 'Phish'),
            (2, 'Frequent', '2019-01-01', '2019-01-01', 'Phish'),
            (3, 'Rare',     '2019-01-01', '2019-01-01', 'Phish'),
            (4, 'NeverPlayed','2019-01-01','2019-01-01', 'Phish');
        """
    )
    # 40 shows, monotonically increasing dates. Song 1 every show, song 2 most
    # shows, song 3 rarely, song 4 never.
    for i in range(40):
        show_id = 1000 + i
        show_date = f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        c.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at, tour_id, tour_position) "
            "VALUES (?, ?, ?, 1, ?)",
            (show_id, show_date, show_date, i + 1),
        )
        rows = [(show_id, "1", 1, 1)]
        if i % 2 == 0:
            rows.append((show_id, "1", 2, 2))
        if i % 13 == 0:
            rows.append((show_id, "1", 3, 3))
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (?,?,?,?)",
            rows,
        )
    c.commit()
    return c


def test_features_are_leak_free(tmp_path):
    """total_plays_ever for a show must count only plays STRICTLY before it."""
    conn = _build_db(tmp_path / "incl.db")
    hist = InclusionHistory(conn)
    idx = INCLUSION_FEATURE_COLUMNS.index("total_plays_ever")

    # Song 1 plays in every show; at the k-th show it should have k prior plays.
    shows = sorted(hist.shows, key=lambda s: s["show_date"])
    for k in (5, 10, 20):
        ctx = hist.context_for(shows[k]["show_id"])
        row = hist.feature_row(1, ctx)
        assert row is not None
        assert row[idx] == k, f"expected {k} prior plays, got {row[idx]}"
    conn.close()


def test_candidate_excludes_never_played(tmp_path):
    conn = _build_db(tmp_path / "incl.db")
    hist = InclusionHistory(conn)
    last = sorted(hist.shows, key=lambda s: s["show_date"])[-1]
    ctx = hist.context_for(last["show_id"])
    cands = hist.candidate_ids(ctx.show_date)
    assert 1 in cands and 2 in cands
    assert 4 not in cands  # never played -> not a candidate


def test_train_and_serve_ranks_staple_over_rare(tmp_path):
    conn = _build_db(tmp_path / "incl.db")
    out = tmp_path / "inclusion_model.lgb"
    res = train_inclusion(tmp_path / "incl.db", out, holdout_days=30, num_boost_round=60, warmup_shows=5)
    assert res["recall_at_25"] >= 0.0
    assert Path(out).exists()

    scorer = load_inclusion_scorer(out)
    ranked = likely_tonight(conn, sorted(hist_ids(conn))[-1], scorer, top_n=10)
    names = [r["name"] for r in ranked]
    assert names, "expected non-empty Likely Tonight list"
    assert "NeverPlayed" not in names
    # The every-show staple should outrank the rarely-played song.
    assert names.index("Staple") < names.index("Rare")
    conn.close()


def hist_ids(conn):
    return [r[0] for r in conn.execute("SELECT show_id FROM shows").fetchall()]


def test_scorer_schema_guard(tmp_path):
    """A model trained on a different column set must be rejected at load."""
    conn = _build_db(tmp_path / "incl.db")
    out = tmp_path / "inclusion_model.lgb"
    train_inclusion(tmp_path / "incl.db", out, holdout_days=30, num_boost_round=30, warmup_shows=5)
    # Sanity: the shipped meta matches the serving contract.
    scorer = load_inclusion_scorer(out)
    assert list(scorer.feature_columns) == INCLUSION_FEATURE_COLUMNS
    with pytest.raises(ValueError):
        scorer.assert_compatible_with(["only", "two"])
    conn.close()


# ---------------------------------------------------------------------------
# Run rule + calibration layer (honest chances for the bonus pick)
# ---------------------------------------------------------------------------

import json  # noqa: E402

import numpy as np  # noqa: E402

from phishpicker.inclusion import (  # noqa: E402
    CALIBRATED_MAX,
    CALIBRATED_MIN,
    CALIBRATION_FILENAME,
    RUN_REPEAT_CHANCE,
    InclusionCalibration,
    apply_run_rule,
    inclusion_chances,
    load_inclusion_calibration,
)
from phishpicker.train.inclusion_features import (  # noqa: E402
    InclusionRows,
    build_inclusion_rows,
    played_earlier_in_run,
)
from phishpicker.train.inclusion_runner import walk_forward  # noqa: E402

NIGHT1, NIGHT2 = 5012, 5013  # first two nights of the first run in inclusion_runs_db


def test_run_rule_caps_songs_already_played_this_run():
    out = apply_run_rule(np.array([0.30, 0.001, 0.20]), np.array([True, True, False]))
    assert out.tolist() == pytest.approx([RUN_REPEAT_CHANCE, 0.001, 0.20])
    assert 0 < RUN_REPEAT_CHANCE < 0.01


def test_calibration_interpolates_clips_and_stays_monotone():
    cal = InclusionCalibration(x=(0.0, 0.1, 0.5), y=(0.0, 0.05, 0.6), meta={})
    out = cal.apply(np.array([0.0, 0.05, 0.3, 0.9]))
    assert out.tolist() == pytest.approx([CALIBRATED_MIN, 0.025, 0.325, 0.6])
    grid = np.linspace(0, 1, 501)
    vals = cal.apply(grid)
    assert np.all(np.diff(vals) >= 0)
    assert vals.min() >= CALIBRATED_MIN and vals.max() <= CALIBRATED_MAX


def test_calibration_rejects_non_monotone_mappings():
    with pytest.raises(ValueError):
        InclusionCalibration.from_dict({"x": [0.0, 0.5, 0.2], "y": [0.0, 0.1, 0.2]})
    with pytest.raises(ValueError):
        InclusionCalibration.from_dict({"x": [0.0, 0.5], "y": [0.3, 0.1]})
    with pytest.raises(ValueError):
        InclusionCalibration.from_dict({"x": [0.0, 0.5], "y": [0.1, 1.5]})


def _train(db: Path, tmp_path: Path, **kw) -> Path:
    out = tmp_path / "artifacts" / "inclusion_model.lgb"
    train_inclusion(db, out, holdout_days=30, num_boost_round=20, warmup_shows=3, **kw)
    return out


def test_train_inclusion_writes_a_calibration_keyed_to_the_model(inclusion_runs_db, tmp_path):
    model = _train(inclusion_runs_db, tmp_path, block_shows=4)
    path = model.parent / CALIBRATION_FILENAME
    meta = json.loads(path.read_text())
    import hashlib

    assert meta["model_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
    assert meta["model_trained_through"] == "2024-08-12"
    assert meta["n_predictions"] > 0 and meta["n_shows"] > 0
    assert meta["fit_through"] <= "2024-08-12"
    assert meta["run_repeat_chance"] == RUN_REPEAT_CHANCE
    assert load_inclusion_calibration(path, model) is not None


def test_train_inclusion_can_skip_calibration(inclusion_runs_db, tmp_path):
    model = _train(inclusion_runs_db, tmp_path, calibrate=False)
    assert not (model.parent / CALIBRATION_FILENAME).exists()


def test_load_calibration_absent_mismatched_or_malformed_is_none(inclusion_runs_db, tmp_path):
    model = _train(inclusion_runs_db, tmp_path, block_shows=4)
    path = model.parent / CALIBRATION_FILENAME
    assert load_inclusion_calibration(tmp_path / "nope.json", model) is None
    meta = json.loads(path.read_text())
    path.write_text(json.dumps({**meta, "model_sha256": "0" * 64}))
    assert load_inclusion_calibration(path, model) is None  # paired with another model
    path.write_text("{not json")
    assert load_inclusion_calibration(path, model) is None


def _raw_scores(conn, show_id, scorer):
    hist = InclusionHistory(conn)
    ctx = hist.context_for(show_id)
    feats, kept = hist.feature_matrix(ctx, hist.candidate_ids(ctx.show_date))
    return dict(zip(kept, scorer.score(feats), strict=True)), hist.run_prior_songs(show_id)


def test_likely_tonight_without_calibration_matches_raw_scores_off_run(inclusion_runs_db, tmp_path):
    """No calibration artifact + nothing played earlier in the run = today's output."""
    model = _train(inclusion_runs_db, tmp_path, calibrate=False)
    scorer = load_inclusion_scorer(model)
    conn = open_db(inclusion_runs_db)
    raw, prior = _raw_scores(conn, NIGHT1, scorer)
    assert prior == set()
    got = likely_tonight(conn, NIGHT1, scorer, top_n=10)
    assert {r["song_id"]: r["probability"] for r in got} == {
        s: round(float(p), 4) for s, p in raw.items()
    }


def test_likely_tonight_caps_songs_played_earlier_in_the_run(inclusion_runs_db, tmp_path):
    model = _train(inclusion_runs_db, tmp_path, calibrate=False)
    scorer = load_inclusion_scorer(model)
    conn = open_db(inclusion_runs_db)
    raw, prior = _raw_scores(conn, NIGHT2, scorer)
    assert {1, 3} <= prior  # Staple and Opener were played on night 1
    got = {r["song_id"]: r["probability"] for r in likely_tonight(conn, NIGHT2, scorer, top_n=10)}
    for sid, p in raw.items():
        expected = min(float(p), RUN_REPEAT_CHANCE) if sid in prior else float(p)
        assert got[sid] == round(expected, 4)


def test_likely_tonight_applies_calibration_after_the_run_rule(inclusion_runs_db, tmp_path):
    model = _train(inclusion_runs_db, tmp_path, calibrate=False)
    scorer = load_inclusion_scorer(model)
    cal = InclusionCalibration(x=(0.0, 0.002, 0.5, 1.0), y=(0.0, 0.004, 0.3, 0.5), meta={})
    conn = open_db(inclusion_runs_db)
    raw, prior = _raw_scores(conn, NIGHT2, scorer)
    got = likely_tonight(conn, NIGHT2, scorer, top_n=10, calibration=cal)
    by_id = {r["song_id"]: r["probability"] for r in got}
    for sid, p in raw.items():
        adj = min(float(p), RUN_REPEAT_CHANCE) if sid in prior else float(p)
        assert by_id[sid] == round(float(cal.apply(np.array([adj]))[0]), 4)
    probs = [r["probability"] for r in got]
    assert probs == sorted(probs, reverse=True)


def test_inclusion_chances_ranks_every_candidate_unrounded(inclusion_runs_db, tmp_path):
    """The full list behind Likely Tonight (the bonus pick prices every song):
    every candidate, unrounded, and likely_tonight is its rounded head."""
    model = _train(inclusion_runs_db, tmp_path, calibrate=False)
    scorer = load_inclusion_scorer(model)
    conn = open_db(inclusion_runs_db)
    raw, prior = _raw_scores(conn, NIGHT2, scorer)
    got = inclusion_chances(conn, NIGHT2, scorer)
    assert [sid for sid, _ in got] == [r["song_id"] for r in likely_tonight(conn, NIGHT2, scorer)]
    assert dict(got) == pytest.approx(
        {s: min(float(p), RUN_REPEAT_CHANCE) if s in prior else float(p) for s, p in raw.items()}
    )
    head = likely_tonight(conn, NIGHT2, scorer, top_n=2)
    assert [(r["song_id"], r["probability"]) for r in head] == [
        (sid, round(p, 4)) for sid, p in got[:2]
    ]
    assert inclusion_chances(conn, 999_999, scorer) == []


def test_walk_forward_trains_each_block_only_on_earlier_shows(inclusion_runs_db):
    from datetime import date

    conn = open_db(inclusion_runs_db)
    hist = InclusionHistory(conn)
    rows = build_inclusion_rows(hist, warmup_shows=3)
    flags = played_earlier_in_run(hist, rows.show_ids, rows.song_ids)
    start = date(2024, 7, 1).toordinal()
    wf = walk_forward(rows, flags, start, block_shows=4, num_boost_round=10)

    assert [b["n_shows"] for b in wf.blocks] == [4, 4, 4]
    for b in wf.blocks:
        assert b["trained_through"] < b["start"]
    assert set(rows.show_ids[wf.rows_idx].tolist()) == {5000 + i for i in range(12, 24)}
    np.testing.assert_array_equal(wf.adjusted, apply_run_rule(wf.raw, flags[wf.rows_idx]))

    # Rewriting every label from block 2 on cannot change block 1's predictions.
    later = rows.dates >= date.fromisoformat(wf.blocks[1]["start"]).toordinal()
    flipped = InclusionRows(
        X=rows.X, y=np.where(later, 1 - rows.y, rows.y), dates=rows.dates,
        show_ids=rows.show_ids, song_ids=rows.song_ids,
    )
    wf2 = walk_forward(flipped, flags, start, block_shows=4, num_boost_round=10)
    b1 = wf.block == 0
    np.testing.assert_array_equal(wf.raw[b1], wf2.raw[wf2.block == 0])

    # A forced break starts a new block on that date.
    brk = date(2024, 7, 10).toordinal()
    wf3 = walk_forward(rows, flags, start, block_shows=4, num_boost_round=10, breaks=(brk,))
    assert "2024-07-10" in [b["start"] for b in wf3.blocks]
    assert [b["n_shows"] for b in wf3.blocks] == [4, 1, 4, 3]


def test_cli_train_inclusion_prints_summary_and_writes_artifacts(
    inclusion_runs_db, tmp_path, monkeypatch, capsys
):
    """Regression: the command used `json` without importing it."""
    import sys

    import phishpicker.cli as cli

    monkeypatch.setenv("PHISHNET_API_KEY", "test")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(tmp_path / "unused"))
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "phishpicker", "train", "inclusion",
            "--db", str(inclusion_runs_db), "--out-dir", str(out),
            "--holdout-days", "30", "--iterations", "20", "--warmup-shows", "3",
            "--block-shows", "4",
        ],
    )
    assert cli.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert "recall_at_25" in printed and printed["calibration"]["n_predictions"] > 0
    for name in ("inclusion_model.lgb", "inclusion_model.meta.json", CALIBRATION_FILENAME):
        assert (out / name).exists(), name


def test_app_serves_calibrated_chances_when_the_artifact_is_present(
    inclusion_runs_db, monkeypatch
):
    from fastapi.testclient import TestClient

    data = inclusion_runs_db.parent
    model = data / "inclusion_model.lgb"
    train_inclusion(
        inclusion_runs_db, model, holdout_days=30, num_boost_round=20, warmup_shows=3,
        block_shows=4,
    )
    monkeypatch.setenv("PHISHNET_API_KEY", "test-key")
    monkeypatch.setenv("PHISHPICKER_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("PHISHPICKER_DATA_DIR", str(data))
    from phishpicker.app import create_app

    cal = load_inclusion_calibration(data / CALIBRATION_FILENAME, model)
    scorer = load_inclusion_scorer(model)
    conn = open_db(inclusion_runs_db)
    expected = likely_tonight(conn, NIGHT2, scorer, top_n=10, calibration=cal)
    with TestClient(create_app()) as client:
        assert client.app.state.inclusion_calibration is not None
        r = client.get(f"/likely-tonight/{NIGHT2}?top_n=10")
        assert r.status_code == 200
        assert r.json()["candidates"] == expected

    (data / CALIBRATION_FILENAME).unlink()
    with TestClient(create_app()) as client:
        assert client.app.state.inclusion_calibration is None
        r = client.get(f"/likely-tonight/{NIGHT2}?top_n=10")
        assert r.json()["candidates"] == likely_tonight(conn, NIGHT2, scorer, top_n=10)
