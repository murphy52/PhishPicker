"""Recompute tests/fixtures/versus_calibration.json 'surprise' maps under the
current classify_surprise rule, from the canonical DB, and print the totals.

Run from the api/ directory (paths resolve from this file, so the repo root
works too):
    uv run python ../scripts/recompute_versus_fixture.py [--write]

Prints one line per fixture show: date, picker_total, phish_total, leader.
Without --write it only reports; with --write it rewrites the fixture, after
which the asserted totals in tests/test_versus_calibration.py must match.
"""

import json
import sys
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.scoring import score_versus
from phishpicker.scoring_service import _surprise_weights

REPO = Path(__file__).resolve().parent.parent
FIX_PATH = REPO / "api" / "tests" / "fixtures" / "versus_calibration.json"
DB_PATH = REPO / "api" / "data" / "phishpicker.db"


def main() -> int:
    if not DB_PATH.exists():
        print(
            f"ERROR: DB not found at {DB_PATH}. Run `phishpicker ingest` first.",
            file=sys.stderr,
        )
        return 2
    fix = json.loads(FIX_PATH.read_text())
    conn = open_db(DB_PATH, read_only=True)
    for date, d in fix.items():
        w = _surprise_weights(conn, d["actual"], bustout_song_ids=set(), show_date=date)
        d["surprise"] = {str(k): list(v) for k, v in w.items()}
        out = score_versus(d["bracket"], d["actual"], w)
        print(date, out["picker_total"], out["phish_total"], out["leader"])
    if "--write" in sys.argv:
        FIX_PATH.write_text(json.dumps(fix, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
