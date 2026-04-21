"""Retrospective: diff a saved preview against the actual setlist + nightly-smoke.

Run from the api/ directory:
    uv run python ../scripts/compare_prediction_to_actual.py \\
        --date 2026-04-23 --venue "Sphere Night 4"

Reads:
    data/previews/preview-<date>.json
    data/phishpicker.db
    data/nightly-predictions.jsonl  (optional)

Emits:
    stdout summary
    <retro-dir>/retro-<date>.md  (default: ../docs/retros/)
"""

import argparse
import sys
from pathlib import Path

from phishpicker.db.connection import open_db
from phishpicker.retro import (
    compare,
    load_actual_setlist,
    load_preview,
    load_smoke_record,
    render_markdown,
    render_stdout_summary,
)

DB_PATH = Path("data/phishpicker.db")
PREVIEW_DIR = Path("data/previews")
JSONL_PATH = Path("data/nightly-predictions.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="show date, YYYY-MM-DD")
    parser.add_argument(
        "--retro-dir",
        default="../docs/retros",
        help="where to write retro markdown (default ../docs/retros)",
    )
    parser.add_argument(
        "--venue",
        default="",
        help="venue label for the retro title (e.g. 'Sphere Night 4')",
    )
    args = parser.parse_args()

    preview_path = PREVIEW_DIR / f"preview-{args.date}.json"
    if not preview_path.exists():
        print(f"ERROR: preview JSON not found: {preview_path}", file=sys.stderr)
        print("Run scripts/preview_night4.py first.", file=sys.stderr)
        return 1

    preview = load_preview(preview_path)

    conn = open_db(DB_PATH, read_only=True)
    actual = load_actual_setlist(conn, args.date)
    if not actual:
        print(
            f"ERROR: no setlist for {args.date} in {DB_PATH}. "
            f"Run `phishpicker ingest` first.",
            file=sys.stderr,
        )
        return 2

    smoke = load_smoke_record(JSONL_PATH, args.date)
    if smoke is None:
        print(
            f"NOTE: no nightly-smoke record found for {args.date} (continuing).",
            file=sys.stderr,
        )

    retro = compare(preview, actual, smoke, venue=args.venue)
    print(render_stdout_summary(retro))

    retro_dir = Path(args.retro_dir)
    retro_dir.mkdir(parents=True, exist_ok=True)
    md_path = retro_dir / f"retro-{args.date}.md"
    md_path.write_text(render_markdown(retro))
    print(f"\nWrote retro markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
