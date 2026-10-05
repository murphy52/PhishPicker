"""The live next-song call (/predict, predict_next) must apply the same run
filter as the bracket: a song played earlier in the run is never a candidate.
It feeds scoring snapshots and the push "Next up" line."""

from contextlib import closing
from datetime import date, timedelta

from phishpicker.config import Settings
from phishpicker.db.connection import open_db

LIVE_DATE = "2026-04-23"
LIVE_VENUE = 1597


def _seed_run_mate(song_id: int) -> None:
    """Anchor the live date into a tour at LIVE_VENUE, with the night before
    at the same venue playing `song_id`."""
    prior = (date.fromisoformat(LIVE_DATE) - timedelta(days=1)).isoformat()
    with closing(open_db(Settings().db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (9997, 'Next Song Run Test', '1900-01-01', '2999-12-31')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (?, 'Live Test Venue')",
            (LIVE_VENUE,),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (?, ?, ?, 9997, '1900-01-01', ?)",
            [(90200, LIVE_DATE, LIVE_VENUE, 0), (90201, prior, LIVE_VENUE, 1)],
        )
        conn.execute(
            "INSERT OR REPLACE INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (90201, '1', 1, ?)",
            (song_id,),
        )
        conn.commit()


def _candidate_ids(client, show_id: str) -> list[int]:
    r = client.get(f"/predict/{show_id}")
    assert r.status_code == 200
    return [c["song_id"] for c in r.json()["candidates"]]


def test_next_song_excludes_songs_played_earlier_in_run(seeded_client, live_show_id):
    target = _candidate_ids(seeded_client, live_show_id)[0]
    _seed_run_mate(target)

    assert target not in _candidate_ids(seeded_client, live_show_id)


def test_next_song_run_filter_backfills_missing_venue(seeded_client):
    # Some flows create the live show without a venue; the bracket resolves it
    # from the canonical show on that date, and so must the next-song call.
    show_id = seeded_client.post("/live/show", json={"show_date": LIVE_DATE}).json()["show_id"]
    target = _candidate_ids(seeded_client, show_id)[0]
    _seed_run_mate(target)

    assert target not in _candidate_ids(seeded_client, show_id)
