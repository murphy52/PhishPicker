"""Per-show context features that don't vary by candidate song."""

import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShowContext:
    show_date: str
    day_of_week: int  # Monday=0
    month: int  # 1..12
    era: int  # 1..4
    tour_position: int


def _era_for(show_date: str) -> int:
    """Convert YYYY-MM-DD → era 1..4 per the design doc:
    1.0 = 1983–2000, 2.0 = 2002–2004, 3.0 = 2009–2019, 4.0 = 2020+.

    The gap years (2001, 2005–2008) are rare in the dataset; we bucket them
    into the adjacent era (here: <2002 → 1, <2005 → 2, <2020 → 3, else 4).
    """
    year = int(show_date[:4])
    if year < 2002:
        return 1
    if year < 2005:
        return 2
    if year < 2020:
        return 3
    return 4


def compute_show_context(
    conn: sqlite3.Connection, show_date: str, venue_id: int | None
) -> ShowContext:
    d = date.fromisoformat(show_date)
    if venue_id is None:
        row = conn.execute(
            "SELECT tour_position FROM shows WHERE show_date = ?",
            (show_date,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT tour_position FROM shows WHERE show_date = ? AND venue_id = ?",
            (show_date, venue_id),
        ).fetchone()
    tp = int(row["tour_position"]) if row and row["tour_position"] is not None else 1
    return ShowContext(
        show_date=show_date,
        day_of_week=d.weekday(),
        month=d.month,
        era=_era_for(show_date),
        tour_position=tp,
    )
