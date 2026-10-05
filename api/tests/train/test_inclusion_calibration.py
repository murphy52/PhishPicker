"""Calibration backtest for the show-level 'Likely Tonight' inclusion model."""

import json
import math

import numpy as np
import pytest

from phishpicker.db.connection import open_db
from phishpicker.train.inclusion_calibration import (
    BANDS,
    POINT_LEVELS,
    PROPOSED_BANDS,
    RELIABILITY_EDGES,
    assign_bands,
    band_table,
    brier_score,
    expected_calibration_error,
    expected_points,
    frequency_baseline,
    log_loss,
    nested_calibration,
    per_show_totals,
    reliability_table,
    run_calibration,
    summarize,
    wilson_interval,
)
from phishpicker.train.inclusion_features import (
    InclusionHistory,
    build_inclusion_rows,
    build_training_data,
    played_earlier_in_run,
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
    assert good["top_pick_ev"] == pytest.approx(10 * 0.5)
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


def test_band_top_pick_breaks_ties_like_the_served_list():
    # Serving lists tied calibrated chances by the uncalibrated score, so the
    # player's "top song" is the tied song with the highest tiebreak.
    p = [0.20, 0.20, 0.20, 0.16]
    y = [1, 0, 0, 1]
    good = band_table(p, y, [1, 1, 1, 1], tiebreak=[0.25, 0.30, 0.21, 0.50])[1]
    assert good["top_pick_rate"] == 0.0


def test_proposed_four_band_scheme():
    assert [(b.name, b.lo, b.points) for b in PROPOSED_BANDS] == [
        ("Good bet", 0.15, 10),
        ("Long shot", 0.05, 25),
        ("Deep cut", 0.01, 60),
        ("Wild card", 0.0, 150),
    ]
    probs = [0.5, 0.15, 0.149, 0.05, 0.01, 0.009]
    assert assign_bands(probs, PROPOSED_BANDS).tolist() == [0, 0, 1, 1, 2, 3]
    rows = band_table([0.5, 0.4, 0.1], [1, 0, 1], [1, 1, 1], bands=PROPOSED_BANDS)
    assert [r["band"] for r in rows] == [b.name for b in PROPOSED_BANDS]
    good = rows[0]
    assert good["points"] == 10 and good["hi"] == 1.0
    assert set(good["ev_by_points"]) == {10, 25, 60, 150}
    assert good["ev_at_band_points"] == pytest.approx(0.5 * 10)
    assert good["top_pick_ev"] == pytest.approx(1.0 * 10)  # the .5 song was played
    assert rows[1]["hi"] == 0.15


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
    assert [b["band"] for b in out["bands_4"]] == [b.name for b in PROPOSED_BANDS]
    assert len(out["reliability"]) == len(RELIABILITY_EDGES) - 1


def test_per_show_totals_compare_summed_chances_with_songs_played():
    p = [0.5, 0.5, 0.2, 0.3]
    y = [1, 1, 0, 0]
    out = per_show_totals(p, y, [1, 1, 2, 2], played_all={1: 3, 2: 1})
    assert out["n_shows"] == 2
    assert out["mean_sum_pred"] == pytest.approx(0.75)
    assert out["mean_played_candidates"] == pytest.approx(1.0)
    assert out["mean_played_all"] == pytest.approx(2.0)
    assert out["mean_abs_gap"] == pytest.approx(0.75)


def _synthetic_blocks(seed=1):
    rng = np.random.default_rng(seed)
    n_shows, per_show = 200, 50
    show = np.repeat(np.arange(n_shows), per_show)
    dates = show + 700000
    true = rng.uniform(0.0, 0.3, show.size)
    y = (rng.uniform(0, 1, show.size) < true).astype(int)
    probs = np.clip(true * 2, 0, 1)  # the "model" says twice the true rate
    block = show // 50
    starts = [700000, 700050, 700100, 700150]
    return probs, y, dates, block, starts


def test_nested_calibration_fixes_overconfidence_out_of_sample():
    probs, y, dates, block, starts = _synthetic_blocks()
    cal, fits = nested_calibration(probs, y, dates, block, starts, 700100, calibration_days=100)
    ev = dates >= 700100
    assert np.all(np.isnan(cal[~ev])) and not np.any(np.isnan(cal[ev]))
    assert (
        expected_calibration_error(cal[ev], y[ev])
        < expected_calibration_error(probs[ev], y[ev]) / 3
    )
    assert [f["block"] for f in fits] == [2, 3]
    for f in fits:
        assert f["fit_through"] < f["start"]
        assert f["n_predictions"] == 100 * 50


def test_nested_calibration_only_sees_the_window_before_each_block():
    probs, y, dates, block, starts = _synthetic_blocks()
    base, _ = nested_calibration(probs, y, dates, block, starts, 700100, calibration_days=60)
    in_block2 = block == 2
    # Labels from block 2 onward, or older than the 60-day window, can't move block 2.
    for changed in (dates >= 700100, dates < 700040):
        y2 = np.where(changed, 1 - y, y)
        cal2, _ = nested_calibration(probs, y2, dates, block, starts, 700100, calibration_days=60)
        np.testing.assert_array_equal(base[in_block2], cal2[in_block2])
    # ...but labels inside the window do.
    y3 = np.where((dates >= 700040) & (dates < 700100), 1 - y, y)
    cal3, _ = nested_calibration(probs, y3, dates, block, starts, 700100, calibration_days=60)
    assert not np.array_equal(base[in_block2], cal3[in_block2])


# ------------------------------------------------------- DB-backed helpers


def test_build_inclusion_rows_matches_training_data_and_carries_song_ids(inclusion_runs_db):
    conn = open_db(inclusion_runs_db)
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


def test_tonights_setlist_never_reaches_tonights_features(inclusion_runs_db):
    """Changing a show's own setlist must not change its feature rows."""
    conn = open_db(inclusion_runs_db)
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


def test_frequency_baseline_is_trailing_12_month_play_rate(inclusion_runs_db):
    conn = open_db(inclusion_runs_db)
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


def test_played_earlier_in_run_scopes_to_venue_and_tour(inclusion_runs_db):
    conn = open_db(inclusion_runs_db)
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
    assert hist.run_prior_songs(run1[2]) == {1, 2, 3}
    # Tour-1 one-offs never flag.
    tour1 = [5000 + i for i in range(3, 12)]
    assert not any(v for (s, _), v in by_key.items() if s in tour1)
    # Venue 1 again on tour 2 is a different residency from its tour-1 visit.
    assert not any(v for (s, _), v in by_key.items() if s == 5000 + 21)
    assert int(flag.sum()) > 0


_PERIOD_KEYS = {"raw", "run_rule", "calibrated", "baseline", "totals", "coverage", "run_slice"}


def test_run_calibration_end_to_end_writes_json(inclusion_runs_db, tmp_path):
    out = tmp_path / "out"
    from phishpicker.train.inclusion_runner import train_inclusion

    art = tmp_path / "art" / "inclusion_model.lgb"
    train_inclusion(
        inclusion_runs_db,
        art,
        holdout_days=30,
        num_boost_round=20,
        warmup_shows=3,
        calibrate=False,
    )
    result = run_calibration(
        inclusion_runs_db,
        cutoff="2024-07-08",
        out_dir=out,
        recent_from="2024-07-15",
        artifact_path=art,
        artifact_trained_through="2024-07-08",
        num_boost_round=20,
        warmup_shows=3,
        block_shows=3,
        calibration_days=200,
    )
    data = json.loads((out / "inclusion_calibration.json").read_text())
    assert data == json.loads(json.dumps(result))  # the file holds every number
    assert data["config"]["cutoff"] == "2024-07-08"
    assert data["config"]["block_shows"] == 3
    full, recent = data["periods"]["full"], data["periods"]["recent"]
    assert set(full) >= _PERIOD_KEYS and set(recent) >= _PERIOD_KEYS
    assert full["raw"]["n_shows"] == 9 and recent["raw"]["n_shows"] == 6
    for period in (full, recent):
        n = period["raw"]["n_predictions"]
        assert n > 0
        assert period["run_rule"]["n_predictions"] == period["calibrated"]["n_predictions"] == n
        assert set(period["totals"]) == {"raw", "run_rule", "calibrated"}
        assert len(period["calibrated"]["bands_4"]) == 4
    # The run rule only ever lowers chances.
    assert full["run_rule"]["mean_pred"] <= full["raw"]["mean_pred"]
    for f in data["calibration_fits"]:
        assert f["fit_through"] < f["start"] and f["start"] >= "2024-07-08"
    prod = data["production_artifact"]
    assert prod["n_shows"] == 8  # shows strictly after 2024-07-08
    assert prod["artifact"]["n_predictions"] == prod["artifact_run_rule"]["n_predictions"]
    assert "chart" in data  # path or the reason it was skipped


def test_cli_eval_inclusion_calibration_needs_no_api_settings(
    inclusion_runs_db, tmp_path, monkeypatch
):
    import sys

    import phishpicker.cli as cli

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
            str(inclusion_runs_db),
            "--cutoff",
            "2024-07-08",
            "--out",
            str(out),
            "--iterations",
            "20",
            "--warmup-shows",
            "3",
            "--block-shows",
            "3",
            "--calibration-days",
            "200",
        ],
    )
    assert cli.main() == 0
    data = json.loads((out / "inclusion_calibration.json").read_text())
    assert data["production_artifact"] is None  # no --artifact given
    # Default: 182 days before the last show, but never before the cutoff.
    assert data["config"]["recent_from"] == "2024-07-08"
