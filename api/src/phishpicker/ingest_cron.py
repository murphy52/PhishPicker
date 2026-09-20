"""Daily ingest sidecar.

Runs `python -m phishpicker.cli ingest` at startup, then every day at the
configured local-tz hour. Between ingests it ticks the close-out watcher and,
on show days, the phishvs publish (hourly until lock). Lives in its own Docker
container next to the API so it can write to the shared phishpicker.db without
depending on host crontab permissions (which Murphy52 doesn't have on the NAS).

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
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from phishpicker.config import Settings

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


def _daily_pass(*, freeze_today: bool = True) -> None:
    from phishpicker.close_out import daily_pass

    try:
        settings, scorer = _load_scorer()
        result = daily_pass(settings, scorer, datetime.now(UTC), freeze_today=freeze_today)
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


def _ingest_and_pass(publish_state: dict, now: datetime) -> None:
    """Daily ingest + close-out pass. A successful ingest unlocks the phishvs
    publish for today; a failed one also skips tonight's bracket freeze (it
    would predate last night's setlist) and leaves the previous bundle
    standing — on a show day the loop retries every INGEST_RETRY."""
    from phishpicker.publish import mark_ingested

    ok = _run_ingest() == 0
    publish_state["last_ingest_attempt_at"] = now
    if ok:
        mark_ingested(publish_state, now)
    _daily_pass(freeze_today=ok)


def _publish_tick(settings: Settings, state: dict, now: datetime) -> None:
    from phishpicker.publish import DEFAULT_LOCK_LOCAL, publish_tick

    def load_scorer():
        return _load_scorer()[1]

    try:
        lock_local = os.environ.get("PHISHVS_LOCK_LOCAL", DEFAULT_LOCK_LOCAL)
        publish_tick(settings, load_scorer, state, now, lock_local=lock_local)
    except Exception:
        log.exception("ingest-cron: publish tick failed")


def _loop_tick(settings: Settings, state: dict, publish_state: dict, now: datetime) -> None:
    """Everything one iteration does besides the scheduled ingest.

    Every step guards itself, because the caller is a bare `while True`: an
    exception escaping here kills the sidecar and takes the close-out watcher
    with it. `ingest_retry_due` opens the database read-only, which raises
    outright when the file does not exist yet — a fresh deploy whose first
    ingest failed — so the most likely crash was also the least visible.

    The watcher runs whatever else happened. Closing out a show is the one
    thing here that cannot wait for the next tick.
    """
    from phishpicker.publish import configured, ingest_retry_due

    if not configured(settings):
        _watch_tick(state)
        return

    try:
        retry_due = ingest_retry_due(settings, publish_state, now)
    except Exception:
        log.exception("ingest-cron: ingest retry check failed")
        retry_due = False

    if retry_due:
        log.info("ingest-cron: show day, retrying the failed ingest")
        try:
            _ingest_and_pass(publish_state, now)
        except Exception:
            log.exception("ingest-cron: retry ingest failed")

    _watch_tick(state)
    _publish_tick(settings, publish_state, now)


def main() -> None:
    from phishpicker.config import Settings
    from phishpicker.publish import configured

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    tz_name = os.environ.get("INGEST_CRON_TZ", DEFAULT_TZ)
    hour = int(os.environ.get("INGEST_CRON_HOUR", DEFAULT_HOUR))
    tick_s = int(os.environ.get("CLOSE_OUT_TICK_SECONDS", TICK_SECONDS))
    tz = ZoneInfo(tz_name)
    log.info(
        "ingest-cron: daily ingest at %02d:00 %s; close-out watcher and phishvs publish every %ds",
        hour,
        tz_name,
        tick_s,
    )
    # Run once at startup so a fresh deploy refreshes the DB without waiting
    # up to 24h. Tolerates phish.net being briefly unavailable; the next
    # scheduled run will pick up whatever was missed.
    #
    # `state` (show_date -> fingerprints seen) lives here so quiescence is
    # measured across ticks. `publish_state` (ingested date, last publish
    # time) gates the phishvs publish on this process's own ingest — a restart
    # after 11am re-ingests here before it publishes anything.
    state: dict = {}
    publish_state: dict = {}
    settings = Settings()
    if not configured(settings):
        log.info("ingest-cron: PHISHVS_PUBLISH_* not set; phishvs publish disabled")
    _ingest_and_pass(publish_state, datetime.now(UTC))
    next_ingest = next_run_at(datetime.now(tz), hour=hour, tz=tz)

    # Tick loop rather than sleeping straight through to the next ingest: the
    # close-out watcher has to poll on show nights, which is nowhere near 11am.
    while True:
        now = datetime.now(tz)
        if now >= next_ingest:
            # Advance the schedule first: an ingest that throws must not leave
            # next_ingest in the past and re-run on every tick after it.
            next_ingest = next_run_at(now, hour=hour, tz=tz)
            try:
                _ingest_and_pass(publish_state, datetime.now(UTC))
            except Exception:
                log.exception("ingest-cron: scheduled ingest failed")
        _loop_tick(settings, state, publish_state, datetime.now(UTC))
        time.sleep(tick_s)


if __name__ == "__main__":
    main()
