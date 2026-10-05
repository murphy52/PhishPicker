"""Nightly live.db backup (#35).

live.db is the one prod database phish.net can't rebuild: scorecards, frozen
brackets, publish_log and push subscriptions. These tests pin the three things
that matter for a backup of a database the API is writing to: the copy holds
exactly what was committed (WAL frames included, the open transaction
excluded), old copies rotate out, and a failure never reaches the cron loop.
"""

import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from phishpicker.backup import BackupError, backup_sqlite
from phishpicker.db.connection import apply_live_schema

DAY = date(2026, 10, 6)


def _subscribe(conn: sqlite3.Connection, n: int, prefix: str = "ep") -> None:
    conn.executemany(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, subscribed_at) VALUES (?, 'k', 'a', 't')",
        [(f"{prefix}{i}",) for i in range(n)],
    )


def _endpoints(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return [
            r[0] for r in conn.execute("SELECT endpoint FROM push_subscriptions ORDER BY endpoint")
        ]


@pytest.fixture
def live_db(tmp_path) -> Path:
    """A real live.db (schema applied, so WAL mode) with three committed rows."""
    path = tmp_path / "live.db"
    with closing(sqlite3.connect(path)) as conn:
        apply_live_schema(conn)
        _subscribe(conn, 3)
        conn.commit()
    return path


def test_copy_holds_committed_rows_while_a_writer_has_uncommitted_wal_frames(tmp_path):
    src = tmp_path / "live.db"
    writer = sqlite3.connect(src, isolation_level=None)
    apply_live_schema(writer)
    # No auto-checkpoint: the committed rows stay in live.db-wal, not live.db.
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    _subscribe(writer, 3)
    # A tiny page cache forces the open transaction to spill its pages into the
    # WAL before it commits, so the -wal file holds frames nobody committed.
    writer.execute("PRAGMA cache_size = 10")
    wal = Path(f"{src}-wal")
    committed_wal = wal.stat().st_size
    writer.execute("BEGIN")
    _subscribe(writer, 500, prefix="uncommitted-" + "x" * 500)
    assert wal.stat().st_size > committed_wal

    # Guard that the test means something: copying the main file alone loses
    # rows that are committed but only live in the WAL.
    naive = shutil.copy(src, tmp_path / "naive.db")
    with closing(sqlite3.connect(naive)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0

    copy = backup_sqlite(src, tmp_path / "backups", day=DAY)

    assert copy == tmp_path / "backups" / "live-2026-10-06.db"
    assert _endpoints(copy) == ["ep0", "ep1", "ep2"]
    # The backup took no lock the writer cares about.
    writer.execute("COMMIT")
    assert len(_endpoints(src)) == 503
    writer.close()


def test_copy_is_one_standalone_file_that_passes_integrity_check(live_db, tmp_path):
    copy = backup_sqlite(live_db, tmp_path / "backups", day=DAY)

    with closing(sqlite3.connect(copy)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    # Restoring is "copy this one file back": no -wal or -shm beside it, and
    # no temp file left behind.
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == ["live-2026-10-06.db"]


def test_rotation_keeps_the_newest_n_and_ignores_other_files(live_db, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    (dest / "notes.txt").write_text("not a backup")

    for i in range(9):
        backup_sqlite(live_db, dest, day=DAY + timedelta(days=i), keep=7)

    copies = sorted(p.name for p in dest.glob("live-*.db"))
    assert copies == [f"live-{(DAY + timedelta(days=i)).isoformat()}.db" for i in range(2, 9)]
    assert (dest / "notes.txt").exists()


def test_a_rerun_the_same_day_replaces_that_days_copy(live_db, tmp_path):
    dest = tmp_path / "backups"
    backup_sqlite(live_db, dest, day=DAY)
    with closing(sqlite3.connect(live_db)) as conn:
        _subscribe(conn, 1, prefix="later")
        conn.commit()

    copy = backup_sqlite(live_db, dest, day=DAY)

    assert "later0" in _endpoints(copy)


def test_overwrite_false_leaves_todays_copy_alone(live_db, tmp_path):
    """The startup run: a deploy at 3pm must not replace the copy made at 5am."""
    dest = tmp_path / "backups"
    first = backup_sqlite(live_db, dest, day=DAY)
    with closing(sqlite3.connect(live_db)) as conn:
        _subscribe(conn, 1, prefix="later")
        conn.commit()

    assert backup_sqlite(live_db, dest, day=DAY, overwrite=False) is None
    assert "later0" not in _endpoints(first)
    # A day with no copy yet still gets one.
    assert backup_sqlite(live_db, dest, day=DAY + timedelta(days=1), overwrite=False) is not None


def test_a_stale_temp_file_from_a_killed_run_is_cleared(live_db, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    for name in (".live-backup.tmp", ".live-backup.tmp-wal", ".live-backup.tmp-shm"):
        (dest / name).write_bytes(b"junk from a container killed mid-backup")

    copy = backup_sqlite(live_db, dest, day=DAY)

    assert _endpoints(copy) == ["ep0", "ep1", "ep2"]
    assert sorted(p.name for p in dest.iterdir()) == ["live-2026-10-06.db"]


def test_a_missing_source_raises_and_is_not_created(tmp_path):
    src = tmp_path / "live.db"

    with pytest.raises(FileNotFoundError):
        backup_sqlite(src, tmp_path / "backups", day=DAY)

    # sqlite3.connect would have quietly created an empty live.db.
    assert not src.exists()


def test_a_corrupt_copy_is_rejected_and_older_copies_survive(tmp_path):
    src = tmp_path / "live.db"
    with closing(sqlite3.connect(src)) as conn:
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.execute("CREATE INDEX t_x ON t (x)")
        conn.executemany("INSERT INTO t VALUES (?)", [(f"row{i}",) for i in range(50)])
        conn.commit()
        root = conn.execute("SELECT rootpage FROM sqlite_master WHERE name = 't_x'").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    dest = tmp_path / "backups"
    good = backup_sqlite(src, dest, day=DAY, keep=1)

    # Scribble over the index's cell pointers. The backup API copies pages
    # without parsing them, so only integrity_check can catch this.
    with open(src, "r+b") as f:
        f.seek((root - 1) * page_size + 8)
        f.write(b"\xff" * 64)

    with pytest.raises(BackupError, match="integrity_check"):
        backup_sqlite(src, dest, day=DAY + timedelta(days=1), keep=1)

    # keep=1, yet the good copy is still there: rotation only runs after a
    # copy passes, so a run of bad nights can't evict the last good one.
    assert sorted(p.name for p in dest.iterdir()) == [good.name]


def test_keep_below_one_is_rejected(live_db, tmp_path):
    with pytest.raises(ValueError):
        backup_sqlite(live_db, tmp_path / "backups", day=DAY, keep=0)


# --- ingest-cron wiring -----------------------------------------------------


class _Settings:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.live_db_path = data_dir / "live.db"


NOW = datetime(2026, 10, 6, 5, 0, tzinfo=ZoneInfo("America/New_York"))


def test_cron_backup_defaults_to_a_backups_dir_under_data(live_db, tmp_path, monkeypatch):
    from phishpicker import ingest_cron as cron

    monkeypatch.delenv("LIVE_DB_BACKUP_DIR", raising=False)
    monkeypatch.delenv("LIVE_DB_BACKUP_KEEP", raising=False)

    cron._backup_live_db(_Settings(tmp_path), NOW)

    assert _endpoints(tmp_path / "backups" / "live-2026-10-06.db") == ["ep0", "ep1", "ep2"]


def test_cron_backup_honours_the_configured_dir_and_keep(live_db, tmp_path, monkeypatch):
    from phishpicker import ingest_cron as cron

    elsewhere = tmp_path / "other-volume"
    monkeypatch.setenv("LIVE_DB_BACKUP_DIR", str(elsewhere))
    monkeypatch.setenv("LIVE_DB_BACKUP_KEEP", "2")

    for i in range(3):
        cron._backup_live_db(_Settings(tmp_path), NOW + timedelta(days=i))

    assert sorted(p.name for p in elsewhere.iterdir()) == [
        "live-2026-10-07.db",
        "live-2026-10-08.db",
    ]
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    ("setup", "env"),
    [
        pytest.param(lambda data: None, {}, id="no live.db yet"),
        pytest.param(
            lambda data: (data / "live.db").write_bytes(b"not a database" * 100),
            {},
            id="garbage file",
        ),
        pytest.param(
            lambda data: sqlite3.connect(data / "live.db").close(),
            {"LIVE_DB_BACKUP_KEEP": "seven"},
            id="bad keep",
        ),
    ],
)
def test_cron_backup_failure_is_logged_not_raised(tmp_path, monkeypatch, caplog, setup, env):
    """The loop is a bare `while True`: an exception escaping here would kill
    the sidecar and the close-out watcher with it."""
    from phishpicker import ingest_cron as cron

    data = tmp_path / "data"
    data.mkdir()
    setup(data)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    cron._backup_live_db(_Settings(data), NOW)

    assert "live.db backup failed" in caplog.text
