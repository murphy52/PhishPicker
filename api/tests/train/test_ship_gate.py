import json

from phishpicker.train.ship_gate import ship_gate_check


def test_first_ship_always_passes(tmp_path):
    metrics_path = tmp_path / "metrics.json"
    assert ship_gate_check(new_mrr=0.10, previous_metrics_path=metrics_path) is True


def test_ship_passes_when_new_is_better(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.15}))
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p) is True


def test_ship_passes_when_regression_within_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # 0.005 drop, tolerance 0.02 → OK.
    assert ship_gate_check(new_mrr=0.195, previous_metrics_path=p) is True


def test_ship_fails_when_regression_exceeds_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # 0.03 drop > 0.02 tolerance → block.
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p) is False


def test_custom_tolerance(tmp_path):
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"mrr": 0.20}))
    # With tolerance 0.05 a 0.03 drop is OK.
    assert ship_gate_check(new_mrr=0.17, previous_metrics_path=p, max_drop=0.05) is True
