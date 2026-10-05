"""What the model can say about itself: GET /about, and the `model` block the
phishvs publish carries so its About PhishPicker page keeps itself current.

/about is metrics.json verbatim. The training run that ships model.lgb writes
it in the same atomic step (train/runner.py), so its numbers — the
walk-forward test, the gain behind each feature — are the deployed model's.
The publish adds two views of data the NAS already serves: PhishPicker's
record against Phish (GET /scorecards' versus totals) and each signal's share
of the model's gain (the page's "What it pays attention to").
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from phishpicker.scoring_service import list_scorecards


def read_metrics(path: Path) -> dict | None:
    """metrics.json from the last shipped training run; None before any."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def versus_record(live_conn: sqlite3.Connection) -> list[dict]:
    """PhishPicker's points and Phish's for every scored show, oldest first.
    Shows scored before the vs game existed, or whose bracket never froze,
    have no result and are left out."""
    record = [
        {"date": c["show_date"], "picker": c["versus_picker"], "phish": c["versus_phish"]}
        for c in list_scorecards(live_conn)
        if c["versus_picker"] is not None and c["versus_phish"] is not None
    ]
    return sorted(record, key=lambda r: r["date"])


def signal_shares(metrics: dict) -> list[dict]:
    """Each feature's share of the model's total gain, in percent, largest
    first. Full precision: the page rounds for display, and rounding here too
    would round twice (57.447 -> 57.45 -> 57.5)."""
    gains = metrics.get("feature_importance_gain") or {}
    total = sum(gains.values())
    if total <= 0:
        return []
    shares = [{"feature": f, "share": 100 * g / total} for f, g in gains.items()]
    return sorted(shares, key=lambda s: (-s["share"], s["feature"]))


def model_stats(live_conn: sqlite3.Connection, metrics_path: Path) -> dict | None:
    """The publish's `model` block, or None before any training has shipped.
    `as_of` is the last show in the record (the page's "Through <date>")."""
    metrics = read_metrics(metrics_path)
    if metrics is None:
        return None
    record = versus_record(live_conn)
    return {
        "as_of": record[-1]["date"] if record else None,
        "about": metrics,
        "record": record,
        "signals": signal_shares(metrics),
    }
