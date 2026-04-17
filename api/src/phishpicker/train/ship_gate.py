"""Ship gate: block training runs that regress MRR beyond tolerance.

The previous production `metrics.json` sits next to `model.lgb` in the shared
data dir. If that file is missing (first ship), we default to PASS. Otherwise,
the new MRR must stay within `max_drop` of the previous MRR. Override is an
explicit caller choice — this module just returns a bool.
"""

import json
from pathlib import Path


def ship_gate_check(
    new_mrr: float,
    previous_metrics_path: Path,
    max_drop: float = 0.02,
) -> bool:
    path = Path(previous_metrics_path)
    if not path.exists():
        return True
    prev = json.loads(path.read_text())
    prev_mrr = float(prev.get("mrr", 0.0))
    return new_mrr >= prev_mrr - max_drop
