import argparse
import sys

from phishpicker.config import Settings
from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
from phishpicker.ingest.pipeline import run_full_ingest
from phishpicker.phishnet.client import PhishNetClient


def main() -> int:
    parser = argparse.ArgumentParser(prog="phishpicker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="initialize local sqlite databases")
    sub.add_parser("ingest", help="full phish.net ingest")
    args = parser.parse_args()

    s = Settings()  # type: ignore[call-arg]

    if args.cmd == "init-db":
        conn = open_db(s.db_path)
        apply_schema(conn)
        live = open_db(s.live_db_path)
        apply_live_schema(live)
        print(f"Initialized {s.db_path} and {s.live_db_path}")
        return 0

    if args.cmd == "ingest":
        with PhishNetClient(api_key=s.phishnet_api_key, base_url=s.phishnet_base_url) as client:
            conn = open_db(s.db_path)
            stats = run_full_ingest(conn, client)
        print(f"Ingest complete: {stats}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
