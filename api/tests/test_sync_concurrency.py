"""Concurrency regression: two overlapping sync_show_with_phishnet calls must
not double-append the setlist.

Root cause of the 2026-07-17 corruption: sync does a read-modify-write
(read live_songs -> reconcile -> append) with no serialization, and the app
triggers sync from several places at once (the 15s foreground poll, /sync/now,
the poller, the close-out watcher). Two overlapping calls both read the same
stale live_songs and both append the new songs -> adjacent-pair duplicates
(BA, BA, CZ, CZ, ...). See fix: a per-show lock around the critical section.
"""
import threading
import time

from phishpicker.db.connection import open_db
from phishpicker.live_sync import sync_show_with_phishnet

# A clean 4-song set-1, as phish.net returns it.
NET = [
    {"songid": 100, "song": "Chalk Dust Torture", "set": "1", "position": 1,
     "artist_name": "Phish"},
    {"songid": 101, "song": "Tweezer", "set": "1", "position": 2,
     "artist_name": "Phish"},
    {"songid": 102, "song": "Wilson", "set": "1", "position": 3,
     "artist_name": "Phish"},
    {"songid": 103, "song": "Sample in a Jar", "set": "1", "position": 4,
     "artist_name": "Phish"},
]


def test_concurrent_sync_does_not_duplicate(live_setup, monkeypatch):
    import phishpicker.live_sync as ls

    # No network — both calls see the same canned setlist.
    monkeypatch.setattr(
        ls.PhishNetClient, "fetch_setlist_by_date", lambda self, d: NET
    )
    # Widen the read-modify-write window so the race is deterministic: both
    # threads finish reconcile (read empty) before either finishes appending.
    orig_append = ls.append_song

    def slow_append(*a, **k):
        time.sleep(0.02)
        return orig_append(*a, **k)

    monkeypatch.setattr(ls, "append_song", slow_append)

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def run():
        try:
            barrier.wait()  # start both together
            sync_show_with_phishnet(
                db_path=live_setup.db_path,
                live_db_path=live_setup.live_db_path,
                api_key="k",
                show_id=live_setup.show_id,
                show_date="2026-04-23",
            )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    with open_db(live_setup.live_db_path) as live:
        n = live.execute(
            "SELECT COUNT(*) FROM live_songs WHERE show_id = ?",
            (live_setup.show_id,),
        ).fetchone()[0]
    assert n == len(NET), f"duplicate appends: {n} live_songs rows for {len(NET)} songs"
