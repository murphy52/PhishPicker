"""Dated, rotated copies of a live SQLite database.

Built for live.db: phishpicker.db can be rebuilt from phish.net, but live.db
holds the scorecards, frozen brackets, publish_log and push subscriptions, and
nothing else has them. The ingest-cron sidecar calls `backup_sqlite` nightly.

The copy goes through SQLite's online backup API, never a file copy. live.db
is in WAL mode, so committed rows can sit in live.db-wal for a while; copying
live.db alone would lose them. The backup API reads one consistent snapshot
(WAL frames included, any open transaction excluded) without blocking the API's
writers.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

DEFAULT_KEEP = 7


class BackupError(Exception):
    """The copy was made but failed its integrity check."""


def backup_sqlite(
    src: Path,
    dest_dir: Path,
    *,
    day: date,
    keep: int = DEFAULT_KEEP,
    overwrite: bool = True,
) -> Path | None:
    """Copy `src` to `dest_dir/<stem>-<day>.db` and keep the newest `keep` copies.

    One copy per day: a second run the same day replaces that day's copy, or
    leaves it alone and returns None when `overwrite` is False (the sidecar's
    startup run, so a deploy never replaces the copy the nightly run made).

    The copy is built in a temp file, checked with PRAGMA integrity_check, and
    only then moved into place. Rotation runs after that, so a bad night raises
    BackupError and leaves every older copy where it was.
    """
    if keep < 1:
        raise ValueError(f"keep must be at least 1, got {keep}")
    # Checked up front: sqlite3.connect on a missing path creates an empty DB.
    if not src.exists():
        raise FileNotFoundError(f"no database to back up at {src}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"{src.stem}-{day.isoformat()}.db"
    if final.exists() and not overwrite:
        return None

    tmp = dest_dir / f".{src.stem}-backup.tmp"
    _remove(tmp)  # a container killed mid-backup can leave one behind
    try:
        _copy(src, tmp)
        errors = _integrity_errors(tmp)
        if errors:
            raise BackupError(f"{src.name} copy failed integrity_check: {errors[0][:500]}")
        os.replace(tmp, final)
    finally:
        _remove(tmp)

    _rotate(dest_dir, src.stem, keep)
    return final


def _copy(src: Path, dest: Path) -> None:
    # mode=ro: the backup can never write to live.db.
    source_uri = f"{src.resolve().as_uri()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source,
        closing(sqlite3.connect(dest)) as target,
    ):
        source.execute("PRAGMA busy_timeout = 15000")
        source.backup(target)
        # The copy inherits WAL mode. Switch it back so the backup is one
        # self-contained file: restoring is copying it over live.db.
        target.execute("PRAGMA journal_mode = DELETE")


def _integrity_errors(path: Path) -> list[str]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    return [] if rows == ["ok"] else rows


def _rotate(dest_dir: Path, stem: str, keep: int) -> None:
    # Only our own dated copies; anything else in the directory is left alone.
    # ISO dates sort lexicographically, so name order is date order.
    dated = re.compile(rf"{re.escape(stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.db")
    copies = sorted(p for p in dest_dir.iterdir() if dated.fullmatch(p.name))
    for old in copies[:-keep]:
        old.unlink()


def _remove(db: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
