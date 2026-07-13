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
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

DEFAULT_TZ = "America/New_York"
DEFAULT_HOUR = 11

# Cadence of the close-out watcher. QUIET_POLLS (2) ticks at this interval is the
# ~20 minutes of no-edits that means a setlist has gone quiet.
TICK_SECONDS = 600


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


def _load_scorer():
    """Load the runtime scorer fresh. Called per daily pass so a reshipped model
    is picked up without restarting the sidecar."""
    from phishpicker.config import Settings
    from phishpicker.model.scorer import load_runtime_scorer

    settings = Settings()
    # Mirrors app.py: the model path is derived from data_dir, not a Settings field.
    return settings, load_runtime_scorer(settings.data_dir / "model.lgb")


def _daily_pass() -> None:
    from phishpicker.close_out import daily_pass

    try:
        settings, scorer = _load_scorer()
        result = daily_pass(settings, scorer, datetime.now(UTC))
        log.info("ingest-cron: daily pass %s", result)
    except Exception:
        log.exception("ingest-cron: daily pass failed")


def _watch_tick(state: dict) -> None:
    from phishpicker.close_out import tick

    try:
        settings, scorer = _load_scorer()
        closed = tick(settings, scorer, state, datetime.now(UTC))
        if closed:
            log.info("ingest-cron: closed out %s", closed)
    except Exception:
        log.exception("ingest-cron: watcher tick failed")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    tz_name = os.environ.get("INGEST_CRON_TZ", DEFAULT_TZ)
    hour = int(os.environ.get("INGEST_CRON_HOUR", DEFAULT_HOUR))
    tick_s = int(os.environ.get("CLOSE_OUT_TICK_SECONDS", TICK_SECONDS))
    tz = ZoneInfo(tz_name)
    log.info(
        "ingest-cron: daily ingest at %02d:00 %s; close-out watcher every %ds",
        hour,
        tz_name,
        tick_s,
    )
    # Run once at startup so a fresh deploy refreshes the DB without waiting
    # up to 24h. Tolerates phish.net being briefly unavailable; the next
    # scheduled run will pick up whatever was missed.
    _run_ingest()
    _daily_pass()
    next_ingest = next_run_at(datetime.now(tz), hour=hour, tz=tz)

    # Tick loop rather than sleeping straight through to the next ingest: the
    # close-out watcher has to poll on show nights, which is nowhere near 11am.
    # `state` (show_date -> fingerprints seen) lives here so quiescence is
    # measured across ticks.
    state: dict = {}
    while True:
        now = datetime.now(tz)
        if now >= next_ingest:
            _run_ingest()
            _daily_pass()
            next_ingest = next_run_at(datetime.now(tz), hour=hour, tz=tz)
        _watch_tick(state)
        time.sleep(tick_s)


if __name__ == "__main__":
    main()
