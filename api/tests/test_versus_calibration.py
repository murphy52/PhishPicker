import json
from pathlib import Path

from phishpicker.scoring import score_versus

FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "versus_calibration.json").read_text()
)


def _run(date):
    d = FIX[date]
    surprise = {int(k): tuple(v) for k, v in d["surprise"].items()}
    return score_versus(d["bracket"], d["actual"], surprise)


def test_magic_night_the_picker_wins():
    out = _run("2026-07-12")
    assert out["leader"] == "picker"
    assert out["picker_total"] == 112 and out["phish_total"] == 19


def test_weird_night_the_band_wins():
    out = _run("2026-07-14")
    assert out["leader"] == "phish"
    assert out["picker_total"] == 24 and out["phish_total"] == 35
