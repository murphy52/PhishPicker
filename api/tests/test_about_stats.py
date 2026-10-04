"""The About-page stats: /about's metrics, PhishPicker's record against Phish,
and each signal's share of the model — the `model` block the phishvs publish
carries (see publish.py)."""

import json

from phishpicker.about import model_stats, read_metrics, signal_shares, versus_record
from phishpicker.live import create_live_show

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
    "feature_importance_gain": {"set_position": 10.0, "bigram_prev_to_this": 60.0, "era": 30.0},
}


def _scorecard(live_conn, show_date: str, versus: tuple[int, int] | None) -> None:
    """A finalized scorecard whose payload carries a vs-game result (picker,
    phish), or none — the shape score_live_show stores."""
    show_id = create_live_show(live_conn, show_date, venue_id=1597)
    payload = {"totals": {}}
    if versus is not None:
        picker, phish = versus
        payload["versus"] = {
            "picker_total": picker,
            "phish_total": phish,
            "leader": "picker" if picker > phish else "phish",
        }
    live_conn.execute(
        "INSERT INTO scorecards (show_id, show_date, finalized_at, combined, "
        "foresight_total, live_total, ppps, max_streak, payload) "
        "VALUES (?, ?, 'x', 0, 0, 0, 0, 0, ?)",
        (show_id, show_date, json.dumps(payload)),
    )
    live_conn.commit()


def test_read_metrics_is_metrics_json_verbatim(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(METRICS))
    assert read_metrics(path) == METRICS


def test_read_metrics_none_before_any_training(tmp_path):
    assert read_metrics(tmp_path / "metrics.json") is None


def test_versus_record_oldest_first_and_only_shows_with_a_result(live_conn):
    _scorecard(live_conn, "2026-07-08", (48, 37))
    _scorecard(live_conn, "2026-04-18", None)  # scored before the vs game: no result
    _scorecard(live_conn, "2026-07-07", (22, 53))
    assert versus_record(live_conn) == [
        {"date": "2026-07-07", "picker": 22, "phish": 53},
        {"date": "2026-07-08", "picker": 48, "phish": 37},
    ]


def test_versus_record_empty_without_scorecards(live_conn):
    assert versus_record(live_conn) == []


def test_signal_shares_are_percent_of_total_gain_largest_first():
    assert signal_shares(METRICS) == [
        {"feature": "bigram_prev_to_this", "share": 60.0},
        {"feature": "era", "share": 30.0},
        {"feature": "set_position", "share": 10.0},
    ]


def test_signal_shares_keep_full_precision():
    """Rounding is the page's job: rounding here too would round twice
    (57.447 -> 57.45 -> 57.5 instead of 57.4)."""
    shares = signal_shares({"feature_importance_gain": {"a": 1.0, "b": 2.0}})
    assert shares[0]["share"] == 200 / 3 and shares[1]["share"] == 100 / 3


def test_signal_shares_empty_without_gains():
    assert signal_shares({}) == []
    assert signal_shares({"feature_importance_gain": {"a": 0.0}}) == []


def test_model_stats_shape(tmp_path, live_conn):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(METRICS))
    _scorecard(live_conn, "2026-10-02", (16, 66))
    _scorecard(live_conn, "2026-10-03", (52, 35))
    assert model_stats(live_conn, path) == {
        "as_of": "2026-10-03",
        "about": METRICS,
        "record": [
            {"date": "2026-10-02", "picker": 16, "phish": 66},
            {"date": "2026-10-03", "picker": 52, "phish": 35},
        ],
        "signals": signal_shares(METRICS),
    }


def test_model_stats_as_of_is_none_with_no_record(tmp_path, live_conn):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(METRICS))
    stats = model_stats(live_conn, path)
    assert stats is not None and stats["as_of"] is None and stats["record"] == []


def test_model_stats_none_without_metrics(tmp_path, live_conn):
    assert model_stats(live_conn, tmp_path / "metrics.json") is None
