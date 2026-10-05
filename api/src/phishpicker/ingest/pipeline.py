import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta

from phishpicker.db.connection import apply_schema
from phishpicker.ingest.derive import recompute_run_and_tour_positions
from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show
from phishpicker.ingest.songs import upsert_songs
from phishpicker.ingest.venues import upsert_venues
from phishpicker.phishnet.client import PhishNetClient, PhishNetError

logger = logging.getLogger(__name__)


def upsert_tour_stubs(conn: sqlite3.Connection, shows: list[dict]) -> None:
    """Insert placeholder tour rows for any tour_id referenced by shows.

    Uses INSERT OR IGNORE so real tour data inserted by a future tours loader
    is never overwritten. Any real tour loader must use ON CONFLICT DO UPDATE
    to replace these stubs. Stub names are prefixed with '[stub]' to distinguish
    them from real tour data in production.
    """
    tour_ids = {s["tourid"] for s in shows if s.get("tourid")}
    for tour_id in tour_ids:
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name) VALUES (?, ?)",
            (tour_id, f"[stub] tour {tour_id}"),
        )
    conn.commit()


PHISH_ARTIST_ID = 1

# An incremental run re-fetches the setlists of shows dated within this many
# days. phish.net fixes recent setlists within a day or two (a segue mark, a
# song id); 30 days is generous cover for that, and costs at most ~23 calls (the
# busiest 30 days since 2009). Edits to older shows arrive years late, at
# random — no window catches those, the weekly full sweep does.
RECENT_DAYS = 30

# A run with no full sweep in this many calendar days does one.
FULL_SWEEP_DAYS = 7

# schema_meta key holding when the last full sweep finished (ISO, UTC).
LAST_FULL_SWEEP_KEY = "last_full_ingest_at"


def select_setlist_fetches(
    shows: list[dict],
    *,
    known_ids: set[int],
    today: date,
    full: bool,
    recent_days: int = RECENT_DAYS,
) -> list[dict]:
    """The shows whose setlist this run fetches from phish.net.

    Never a show dated after `today`: it has no setlist yet. A full sweep takes
    every other show. An incremental run takes the shows dated within the last
    `recent_days` (late corrections) and the ones not in the DB before this run
    (new to us, so never fetched). An older show we already have, setlist or
    not, waits for the next full sweep — 200-odd listed shows have no setlist on
    phish.net at all (the cancelled 2020 tour, much of the 1980s), and treating
    them as "missing" would refetch every one of them every day.
    """
    last = today.isoformat()
    first_recent = (today - timedelta(days=recent_days)).isoformat()
    picked = []
    for show in shows:
        show_date = str(show["showdate"])
        if show_date > last:
            continue
        if full or show["showid"] not in known_ids or show_date >= first_recent:
            picked.append(show)
    return picked


def full_sweep_due(last_full_at: datetime | None, now: datetime) -> bool:
    """True when no full sweep has run in the last FULL_SWEEP_DAYS calendar days
    (UTC). Counted in days, not hours, so a daily 11:00 run that starts a few
    seconds earlier than last week's still sweeps on the same weekday."""
    if last_full_at is None:
        return True
    return (now.astimezone(UTC).date() - last_full_at.astimezone(UTC).date()).days >= (
        FULL_SWEEP_DAYS
    )


def _last_full_sweep(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (LAST_FULL_SWEEP_KEY,)
    ).fetchone()
    if row is None:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except ValueError:
        return None


def _record_full_sweep(conn: sqlite3.Connection, at: datetime) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (LAST_FULL_SWEEP_KEY, at.astimezone(UTC).isoformat()),
    )
    conn.commit()


def run_ingest(
    conn: sqlite3.Connection,
    client: PhishNetClient,
    artist_id: int | None = PHISH_ARTIST_ID,
    *,
    full: bool | None = None,
    now: datetime | None = None,
) -> dict:
    """Ingest phish.net into `conn`: songs, venues and the shows list in full
    (one call each), then setlists — every show that has happened on a full
    sweep, only the ones that can still change otherwise (see
    select_setlist_fetches).

    `full=None` (the daily default) sweeps in full only when the last full sweep
    is FULL_SWEEP_DAYS old, or there never was one — so a fresh DB, or one
    whose ingest has been down for a week, gets everything. `full=True` forces
    a sweep, `full=False` forbids one.

    By default filters to artist_id=1 (Phish proper). phish.net's `/shows.json`
    returns side-project gigs (Trey Anastasio Band, Mike Gordon Band, etc.) too;
    including them contaminates the training corpus because a Trey-solo opener
    like "Tilting" gets ranked above Phish openers. Pass artist_id=None to skip
    the filter.
    """
    now = now or datetime.now(UTC)
    # apply_schema is called here defensively so callers that skip `init-db`
    # still get a valid schema; all DDL uses CREATE IF NOT EXISTS so it is idempotent.
    apply_schema(conn)
    if full is None:
        full = full_sweep_due(_last_full_sweep(conn), now)

    songs = client.fetch_songs()
    n_songs = upsert_songs(conn, songs)

    venues = client.fetch_venues()
    n_venues = upsert_venues(conn, venues)

    shows = client.fetch_all_shows()
    if artist_id is not None:
        shows = [s for s in shows if s.get("artistid") == artist_id]
    upsert_tour_stubs(conn, shows)

    known_ids = {r[0] for r in conn.execute("SELECT show_id FROM shows")}
    for show in shows:
        upsert_show(conn, show)
    to_fetch = select_setlist_fetches(
        shows, known_ids=known_ids, today=now.astimezone(UTC).date(), full=full
    )

    n_rows = n_changed = n_errors = 0
    for show in to_fetch:
        try:
            setlist = client.fetch_setlist(show["showid"])
        except PhishNetError as exc:
            logger.warning("setlist fetch failed for show %s: %s", show["showid"], exc)
            n_errors += 1
            continue
        written = upsert_setlist_songs(conn, setlist)
        n_rows += written
        n_changed += written > 0

    recompute_run_and_tour_positions(conn)
    if full:
        _record_full_sweep(conn, now)
    return {
        "mode": "full" if full else "incremental",
        "songs": n_songs,
        "venues": n_venues,
        "shows": len(shows),
        "setlists_fetched": len(to_fetch),
        "setlists_changed": n_changed,
        "setlist_errors": n_errors,
        "setlist_rows": n_rows,
    }
