"""Resolve the 'last show' for the post-show review endpoint.

Same 15-hour rollover lag as /upcoming so the two endpoints flip
atomically at the same boundary (11am EDT day after a show).
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta


def rollover_today(now: datetime) -> str:
    """Return the YYYY-MM-DD date used as 'today' under the 15h rollover.

    Mirrors the cutoff logic in the /upcoming handler: subtract 15h from
    UTC now, take the date. 15h lag = rollover at 15:00 UTC = 11am EDT.
    """
    return (now - timedelta(hours=15)).date().isoformat()


def resolve_last_show_id(
    conn: sqlite3.Connection,
    *,
    today: str | None = None,
) -> int | None:
    """Return the most-recent show_id with setlist rows where
    show_date < today (rollover-adjusted). None when no such show.
    """
    if today is None:
        today = rollover_today(datetime.now(UTC))
    row = conn.execute(
        """
        SELECT s.show_id FROM shows s
        WHERE s.show_date < ?
          AND EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)
        ORDER BY s.show_date DESC, s.show_id DESC
        LIMIT 1
        """,
        (today,),
    ).fetchone()
    return int(row["show_id"]) if row else None
