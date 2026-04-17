import logging
import sqlite3

from phishpicker.db.connection import apply_schema
from phishpicker.ingest.derive import recompute_run_and_tour_positions
from phishpicker.ingest.shows import upsert_setlist_songs, upsert_show
from phishpicker.ingest.songs import upsert_songs
from phishpicker.ingest.venues import upsert_venues
from phishpicker.phishnet.client import PhishNetClient, PhishNetError

logger = logging.getLogger(__name__)


def _upsert_tour_stubs(conn: sqlite3.Connection, shows: list[dict]) -> None:
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


def run_full_ingest(conn: sqlite3.Connection, client: PhishNetClient) -> dict:
    # apply_schema is called here defensively so callers that skip `init-db`
    # still get a valid schema; all DDL uses CREATE IF NOT EXISTS so it is idempotent.
    apply_schema(conn)

    songs = client.fetch_songs()
    n_songs = upsert_songs(conn, songs)

    venues = client.fetch_venues()
    n_venues = upsert_venues(conn, venues)

    shows = client.fetch_all_shows()
    _upsert_tour_stubs(conn, shows)

    n_shows = 0
    n_setlist = 0
    for show in shows:
        upsert_show(conn, show)
        try:
            setlist = client.fetch_setlist(show["showid"])
            n_setlist += upsert_setlist_songs(conn, setlist)
        except PhishNetError as exc:
            logger.warning("setlist fetch failed for show %s: %s", show["showid"], exc)
        n_shows += 1

    recompute_run_and_tour_positions(conn)
    return {"songs": n_songs, "venues": n_venues, "shows": n_shows, "setlist_rows": n_setlist}
