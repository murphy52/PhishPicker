"""Calibration backtest for the show-level 'Likely Tonight' inclusion model."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.inclusion_calibration import (
    BANDS,
    POINT_LEVELS,
    RELIABILITY_EDGES,
    assign_bands,
    band_table,
    brier_score,
    expected_calibration_error,
    expected_points,
    frequency_baseline,
    isotonic_holdout,
    log_loss,
    played_earlier_in_run,
    reliability_table,
    run_calibration,
    summarize,
    wilson_interval,
)
from phishpicker.train.inclusion_features import (
    InclusionHistory,
    build_inclusion_rows,
    build_training_data,
)

# ---------------------------------------------------------------- pure parts


def test_bands_are_the_proposed_bonus_bands_in_order():
    assert [b.name for b in BANDS] == [
        "Safe bet",
        "Good bet",
        "Long shot",
        "Deep cut",
        "Wild card",
    ]
    assert [b.points for b in BANDS] == [5, 10, 20, 40, 75]
    assert POINT_LEVELS == (5, 10, 20, 40, 75)


def test_assign_bands_uses_inclusive_lower_edges():
    probs = [0.9, 0.35, 0.3499, 0.15, 0.10, 0.05, 0.0499, 0.01, 0.0099, 0.0]
    assert assign_bands(probs).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_wilson_interval_known_values():
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    lo, hi = wilson_interval(0, 20)
    assert lo == pytest.approx(0.0, abs=1e-12)
    assert hi == pytest.approx(0.1611, abs=1e-4)


def test_wilson_interval_edges_stay_in_unit_range():
    assert wilson_interval(0, 0) == (0.0, 1.0)  # no data: no information
    lo, hi = wilson_interval(30, 30)
    assert 0.0 <= lo < hi
    assert hi == pytest.approx(1.0, abs=1e-12)


def test_expected_points_is_rate_times_points():
    assert expected_points(0.1) == pytest.approx({5: 0.5, 10: 1.0, 20: 2.0, 40: 4.0, 75: 7.5})
    assert expected_points(0.5, points=(8,)) == {8: 4.0}


def test_brier_score():
    assert brier_score([1.0, 0.0, 0.5], [1, 0, 1]) == pytest.approx(0.25 / 3)


def test_log_loss_and_its_clipping():
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))
    # A 0% call on a song that gets played costs -ln(eps), not infinity.
    assert log_loss([0.0], [1], eps=1e-4) == pytest.approx(-math.log(1e-4))


def test_ece_is_zero_when_rates_match_and_weights_bin_gaps():
    # 10 predictions at 20%, two of them played -> perfectly calibrated.
    p = [0.2] * 10
    y = [1, 1] + [0] * 8
    assert expected_calibration_error(p, y) == pytest.approx(0.0)
    # Half the rows: 2% predicted, never played (gap .02); half: 40% / 40%.
    p = [0.02] * 10 + [0.4] * 10
    y = [0] * 10 + [1] * 4 + [0] * 6
    assert expected_calibration_error(p, y) == pytest.approx(0.5 * 0.02)


def test_reliability_table_bins_every_prediction_once():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 500)
    y = (rng.uniform(0, 1, 500) < p).astype(int)
    rows = reliability_table(p, y)
    assert len(rows) == len(RELIABILITY_EDGES) - 1
    assert sum(r["n"] for r in rows) == 500
    for r in rows:
        if r["n"]:
            assert r["lo"] <= r["mean_pred"] <= r["hi"]
            assert r["ci_low"] <= r["actual_rate"] <= r["ci_high"]
        else:
            assert r["mean_pred"] is None and r["actual_rate"] is None


def test_band_table_counts_rates_and_top_pick():
    # Two shows. Show 1: Safe .50 (played), Good .30 (no), Good .20 (yes),
    # Wild .005 (no). Show 2: Good .25 (yes), Long .10 (no).
    p = [0.50, 0.30, 0.20, 0.005, 0.25, 0.10]
    y = [1, 0, 1, 0, 1, 0]
    shows = [1, 1, 1, 1, 2, 2]
    rows = {r["band"]: r for r in band_table(p, y, shows)}

    good = rows["Good bet"]
    assert good["n"] == 3
    assert good["mean_pred"] == pytest.approx(0.25)
    assert good["actual_rate"] == pytest.approx(2 / 3)
    assert good["songs_per_show"] == pytest.approx(1.5)
    assert good["points"] == 10
    assert good["ev_at_band_points"] == pytest.approx(10 * 2 / 3)
    assert good["ev_by_points"][75] == pytest.approx(75 * 2 / 3)
    # Top pick per show: show 1's best Good bet (.30) missed, show 2's (.25) hit.
    assert good["top_pick_rate"] == pytest.approx(0.5)
    assert good["top_pick_shows"] == 2
    lo, hi = wilson_interval(2, 3)
    assert good["ci_low"] == pytest.approx(lo) and good["ci_high"] == pytest.approx(hi)

    assert good["top_pick_mean_pred"] == pytest.approx((0.30 + 0.25) / 2)
    assert rows["Deep cut"]["n"] == 0
    assert rows["Deep cut"]["actual_rate"] is None
    assert rows["Deep cut"]["songs_per_show"] == 0.0


def test_band_top_pick_averages_over_tied_top_songs():
    # A step-function calibrator ties songs; the "top pick" is then a coin
    # flip among them, so its hit rate is the tied songs' mean.
    p = [0.20, 0.20, 0.20, 0.16]
    y = [1, 0, 0, 1]
    good = band_table(p, y, [1, 1, 1, 1])[1]
    assert good["top_pick_rate"] == pytest.approx(1 / 3)
    assert good["top_pick_mean_pred"] == pytest.approx(0.20)


def test_summarize_reports_overall_metrics():
    p = [0.5, 0.5, 0.02, 0.02]
    y = [1, 0, 0, 0]
    out = summarize(p, y, [1, 1, 2, 2])
    assert out["n_predictions"] == 4
    assert out["n_shows"] == 2
    assert out["base_rate"] == pytest.approx(0.25)
    assert out["mean_pred"] == pytest.approx(0.26)
    assert out["brier"] == pytest.approx(brier_score(p, y))
    assert out["log_loss"] == pytest.approx(log_loss(p, y))
    assert out["ece"] == pytest.approx(expected_calibration_error(p, y))
    assert [b["band"] for b in out["bands"]] == [b.name for b in BANDS]
    assert len(out["reliability"]) == len(RELIABILITY_EDGES) - 1


def test_isotonic_holdout_fits_first_half_and_fixes_overconfidence():
    # The "model" says 2x the true rate. Isotonic fitted on the first half of
    # the shows should pull the second half back toward honest rates.
    rng = np.random.default_rng(1)
    n_shows, per_show = 200, 50
    shows = np.repeat(np.arange(n_shows), per_show)
    dates = shows + 700000
    true = rng.uniform(0.0, 0.3, n_shows * per_show)
    y = (rng.uniform(0, 1, true.size) < true).astype(int)
    probs = np.clip(true * 2, 0, 1)

    out = isotonic_holdout(probs, y, shows, dates)
    assert out["n_fit_shows"] == 100 and out["n_eval_shows"] == 100
    assert out["fit_through"] < out["eval_from"]
    assert out["calibrated"]["ece"] < out["raw"]["ece"] / 3
    assert out["raw"]["n_predictions"] == out["calibrated"]["n_predictions"] == 100 * per_show


# ------------------------------------------------------- DB-backed helpers


def _build_db(path: Path):
    """24 shows over 2024 on two tours. Tour 1: 12 one-offs at distinct venues
    (the last at venue 1). Tour 2: three 3-night runs (venues 2, 3, 4), then
    one-offs at venues 1, 5, 6. A run = same venue + tour (the app's
    residency). Song 1 every show; song 2 every other show; song 3 only on
    night 1 of each run; song 4 rarely; song 5 only on the last show."""
    c = open_db(path)
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO tours (tour_id, name) VALUES (1, 'Spring'), (2, 'Summer');
        INSERT INTO songs (song_id, name, first_seen_at, debut_date, original_artist) VALUES
            (1, 'Staple',   '2019-01-01', '2019-01-01', 'Phish'),
            (2, 'Frequent', '2019-01-01', '2019-01-01', 'Phish'),
            (3, 'Opener',   '2019-01-01', '2019-01-01', 'Phish'),
            (4, 'Rare',     '2019-01-01', '2019-01-01', 'Phish'),
            (5, 'Debut',    '2024-12-01', '2024-12-01', 'Phish');
        """
    )
    c.executemany(
        "INSERT INTO venues (venue_id, name) VALUES (?, ?)", [(v, f"V{v}") for v in range(1, 30)]
    )
    shows = []
    # Tour 1: 12 one-off shows, one per week from Jan 6, at venues 10..20 then 1.
    for i in range(12):
        venue = 1 if i == 11 else 10 + i
        shows.append((f"2024-{1 + i // 4:02d}-{6 + 7 * (i % 4):02d}", venue, 1, 1, 1, i + 1))
    # Tour 2: three 3-night runs at venues 2, 3, 4 (consecutive nights), plus 3 one-offs.
    pos = 0
    for venue, start_day in ((2, 1), (3, 8), (4, 15)):
        for night in range(3):
            pos += 1
            shows.append((f"2024-07-{start_day + night:02d}", venue, 2, night + 1, 3, pos))
    for k, venue in enumerate((1, 5, 6)):
        pos += 1
        shows.append((f"2024-08-{10 + k:02d}", venue, 2, 1, 1, pos))

    for idx, (d, venue, tour, rpos, rlen, tpos) in enumerate(shows):
        show_id = 5000 + idx
        c.execute(
            "INSERT INTO shows (show_id, show_date, venue_id, tour_id, run_position, "
            "run_length, tour_position, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (show_id, d, venue, tour, rpos, rlen, tpos, d),
        )
        songs = [1]
        if idx % 2 == 0:
            songs.append(2)
        if rpos == 1:
            songs.append(3)
        if idx % 7 == 0:
            songs.append(4)
        if idx == len(shows) - 1:
            songs.append(5)
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
            [(show_id, "1", p + 1, s) for p, s in enumerate(songs)],
        )
    c.commit()
    return c


def test_build_inclusion_rows_matches_training_data_and_carries_song_ids(tmp_path):
    conn = _build_db(tmp_path / "c.db")
    hist = InclusionHistory(conn)
    rows = build_inclusion_rows(hist, warmup_shows=3)
    X, y, dates, show_ids = build_training_data(conn, warmup_shows=3)
    np.testing.assert_array_equal(rows.X, X)
    np.testing.assert_array_equal(rows.y, y)
    np.testing.assert_array_equal(rows.dates, dates)
    np.testing.assert_array_equal(rows.show_ids, show_ids)
    assert rows.song_ids.shape == rows.y.shape
    for sid, song, label in zip(rows.show_ids, rows.song_ids, rows.y, strict=True):
        assert label == (1 if int(song) in hist.played_in_show[int(sid)] else 0)


def test_tonights_setlist_never_reaches_tonights_features(tmp_path):
    """Changing a show's own setlist must not change its feature rows."""
    conn = _build_db(tmp_path / "c.db")
    last = 5000 + 23
    before = build_inclusion_rows(InclusionHistory(conn), warmup_shows=3)
    conn.execute("DELETE FROM setlist_songs WHERE show_id = ? AND song_id != 1", (last,))
    conn.execute(
        "INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES (?,?,?,?)",
        (last, "1", 2, 4),
    )
    conn.commit()
    after = build_inclusion_rows(InclusionHistory(conn), warmup_shows=3)
    mb, ma = before.show_ids == last, after.show_ids == last
    np.testing.assert_array_equal(before.song_ids[mb], after.song_ids[ma])
    np.testing.assert_array_equal(before.X[mb], after.X[ma])
    assert not np.array_equal(before.y[mb], after.y[ma])  # only the labels moved


def test_frequency_baseline_is_trailing_12_month_play_rate(tmp_path):
    conn = _build_db(tmp_path / "c.db")
    hist = InclusionHistory(conn)
    rows = build_inclusion_rows(hist, warmup_shows=3)
    base = frequency_baseline(hist, rows)
    # Song 1 plays every show, so its prior-12-month rate is exactly 1.
    assert np.all(base[rows.song_ids == 1] == pytest.approx(1.0))
    # Song 3 opens each run: at the first show of tour 2 (2024-07-01) it has
    # played all 12 prior shows (all one-off night-1s) -> 12/12.
    july1 = 5000 + 12
    m = (rows.show_ids == july1) & (rows.song_ids == 3)
    assert base[m][0] == pytest.approx(1.0)
    # On 2024-07-02 it has played 13 of 13 prior shows; on 07-03, 13 of 14.
    m = (rows.show_ids == july1 + 2) & (rows.song_ids == 3)
    assert base[m][0] == pytest.approx(13 / 14)
    assert np.all((base >= 0) & (base <= 1))


def test_played_earlier_in_run_scopes_to_venue_and_tour(tmp_path):
    conn = _build_db(tmp_path / "c.db")
    hist = InclusionHistory(conn)
    rows = build_inclusion_rows(hist, warmup_shows=3)
    flag = played_earlier_in_run(hist, rows.show_ids, rows.song_ids)
    by_key = {
        (int(s), int(g)): bool(f)
        for s, g, f in zip(rows.show_ids, rows.song_ids, flag, strict=True)
    }
    run1 = [5000 + 12, 5000 + 13, 5000 + 14]  # venue 2, nights 1-3
    # Night 1: nothing is "earlier in the run".
    assert not any(v for (s, _), v in by_key.items() if s == run1[0])
    # Night 2: songs from night 1 (1, 2, 3) are flagged; song 4 was not played.
    assert by_key[(run1[1], 1)] and by_key[(run1[1], 3)]
    assert not by_key[(run1[1], 4)]
    # Night 3: anything from nights 1-2 counts (song 3 opened night 1).
    assert by_key[(run1[2], 3)]
    # Tour-1 one-offs never flag.
    tour1 = [5000 + i for i in range(3, 12)]
    assert not any(v for (s, _), v in by_key.items() if s in tour1)
    # Venue 1 again on tour 2 is a different residency from its tour-1 visit.
    assert not any(v for (s, _), v in by_key.items() if s == 5000 + 21)
    assert int(flag.sum()) > 0


def test_run_calibration_end_to_end_writes_json(tmp_path):
    db = tmp_path / "c.db"
    _build_db(db).close()
    out = tmp_path / "out"
    # Train a stand-in "production artifact" on the same tiny DB.
    from phishpicker.train.inclusion_runner import train_inclusion

    art = tmp_path / "inclusion_model.lgb"
    train_inclusion(db, art, holdout_days=30, num_boost_round=20, warmup_shows=3)

    result = run_calibration(
        db,
        cutoff="2024-07-01",
        out_dir=out,
        artifact_path=art,
        artifact_trained_through="2024-07-08",
        num_boost_round=20,
        warmup_shows=3,
    )
    data = json.loads((out / "inclusion_calibration.json").read_text())
    assert data == json.loads(json.dumps(result))  # the file holds every number
    assert data["config"]["cutoff"] == "2024-07-01"
    assert data["n_test_shows"] == 12
    assert data["model"]["n_predictions"] == data["baseline"]["n_predictions"] > 0
    cov = data["coverage"]
    assert cov["played_pairs"] >= cov["played_pairs_in_candidates"]
    assert cov["missed_debuts"] >= 1  # song 5 debuts at the last show
    # Under 3 years of history: nothing has aged out of the candidate set.
    assert cov["older_songs_per_show"] == 0.0
    assert cov["older_song_play_rate"] is None
    assert data["run_slice"]["model"]["n_predictions"] > 0
    assert set(data["isotonic"]) >= {"raw", "calibrated", "n_fit_shows", "n_eval_shows"}
    prod = data["production_artifact"]
    assert prod["n_shows"] == 8  # shows strictly after 2024-07-08
    assert prod["artifact"]["n_predictions"] == prod["backtest_model_same_shows"]["n_predictions"]
    assert set(prod["run_slice"]) >= {"artifact", "backtest_model"}
    assert "chart" in data  # path or the reason it was skipped


def test_cli_eval_inclusion_calibration_needs_no_api_settings(tmp_path, monkeypatch):
    import sys

    import phishpicker.cli as cli

    db = tmp_path / "c.db"
    _build_db(db).close()
    monkeypatch.delenv("PHISHNET_API_KEY", raising=False)
    monkeypatch.delenv("PHISHPICKER_ADMIN_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here either
    out = tmp_path / "report"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "phishpicker",
            "eval",
            "inclusion-calibration",
            "--db",
            str(db),
            "--cutoff",
            "2024-07-01",
            "--out",
            str(out),
            "--iterations",
            "20",
            "--warmup-shows",
            "3",
        ],
    )
    assert cli.main() == 0
    data = json.loads((out / "inclusion_calibration.json").read_text())
    assert data["production_artifact"] is None  # no --artifact given
