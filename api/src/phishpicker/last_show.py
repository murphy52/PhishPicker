"""Resolve the 'last show' for the post-show review endpoint, and own the
rollover that /upcoming shares.

Both endpoints call rollover_today, so they flip atomically at the same instant —
06:00 EDT the morning after a show. See ROLLOVER_LAG_HOURS for why 6am.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

# Hours subtracted from UTC now to get the date the app treats as "today".
# The lag exists so the flip from one show to the next happens AFTER a show, not
# during it: plain UTC midnight is 8pm ET, before a 7pm show has even ended.
#
# 10h => rollover at 10:00 UTC = 6am EDT (5am EST).
#
# Why not earlier: the binding case is a west-coast show, which ends ~23:30 PT =
# 02:30 ET, with its setlist settling on phish.net an hour or so later. Flip
# before that and /upcoming jumps off a show that is still being played. ~5am ET
# is the floor; 6am keeps margin.
#
# Why not later (it was 15h = 11am EDT): waiting until 11am to see the next show
# is far too late — you want tonight's bracket in the morning.
#
# This depends on close_out writing last night's setlist into the canonical DB
# within ~30 min of it settling (see close_out.close_out_show). resolve_last_show_id
# below requires setlist rows to exist, so without that the 6am flip would leave
# /last-show pointing at the wrong show until the 11am ingest.
ROLLOVER_LAG_HOURS = 10


def rollover_today(now: datetime) -> str:
    """Return the YYYY-MM-DD date the app treats as 'today'.

    THE single definition of the rollover — /upcoming and /last-show must flip
    atomically, so both go through here rather than each re-deriving the lag.
    """
    return (now - timedelta(hours=ROLLOVER_LAG_HOURS)).date().isoformat()


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
