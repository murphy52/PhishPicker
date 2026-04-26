"""Daily ingest sidecar.

Runs `python -m phishpicker.cli ingest` at startup, then every day at the
configured local-tz hour. Lives in its own Docker container next to the API
so it can write to the shared phishpicker.db without depending on host
crontab permissions (which Murphy52 doesn't have on the NAS).

The schedule function is a pure function isolated from the loop body for
testing. Run as `python -m phishpicker.ingest_cron`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

DEFAULT_TZ = "America/New_York"
DEFAULT_HOUR = 11


def next_run_at(now: datetime, *, hour: int, tz: ZoneInfo) -> datetime:
    """Return the next datetime at `hour:00:00` in `tz` strictly after `now`.

    `now` MUST be timezone-aware. We re-anchor it in `tz` to compute the
    next local-clock 11:00, which DST-handles automatically because zoneinfo
    resolves UTC offsets per-instant.
    """
    local = now.astimezone(tz)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target


def _run_ingest() -> int:
    """Invoke the ingest CLI and return its exit code."""
    log.info("ingest-cron: starting phishpicker ingest")
    proc = subprocess.run(
        [sys.executable, "-m", "phishpicker.cli", "ingest"],
        check=False,
    )
    log.info("ingest-cron: ingest exited with code %d", proc.returncode)
    return proc.returncode


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    tz_name = os.environ.get("INGEST_CRON_TZ", DEFAULT_TZ)
    hour = int(os.environ.get("INGEST_CRON_HOUR", DEFAULT_HOUR))
    tz = ZoneInfo(tz_name)
    log.info("ingest-cron: scheduling daily at %02d:00 %s", hour, tz_name)
    # Run once at startup so a fresh deploy refreshes the DB without waiting
    # up to 24h. Tolerates phish.net being briefly unavailable; the next
    # scheduled run will pick up whatever was missed.
    _run_ingest()
    while True:
        now = datetime.now(tz)
        target = next_run_at(now, hour=hour, tz=tz)
        sleep_s = (target - now).total_seconds()
        log.info(
            "ingest-cron: sleeping %.0fs until %s",
            sleep_s,
            target.isoformat(),
        )
        time.sleep(sleep_s)
        _run_ingest()


if __name__ == "__main__":
    main()
