"""Second-batch feature computations for the LightGBM ranker.

Kept separate from `phishpicker.model.stats.compute_song_stats` because that
function is also consumed by the heuristic scorer and frozen SongStats dataclass.
Extended stats are LightGBM-only and live in a plain dict keyed by song_id.

Everything here is a pure function over (conn, show_date, venue_id,
candidate_song_ids) so the trainer can cache shared scans per-fold if
needed in a future optimization pass.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

BUSTOUT_THRESHOLD_SHOWS: int = 50


@dataclass
class ExtendedStats:
    set1_opener_rate: float = 0.0
    set2_opener_rate: float = 0.0
    closer_score: float = 0.0
    encore_rate: float = 0.0
    times_at_venue: int = 0
    venue_debut_affinity: float = 0.0
    debut_year: int = -1
    is_cover: int = 0
    bustout_score: float = 0.0
    days_since_last_played_anywhere: int = -1
    tour_opener_rate: float = 0.0
    tour_closer_rate: float = 0.0


def compute_extended_stats(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    candidate_song_ids: list[int],
) -> dict[int, ExtendedStats]:
    """Return {song_id: ExtendedStats} for the candidates as of show_date."""
    if not candidate_song_ids:
        return {}

    placeholders = ",".join("?" * len(candidate_song_ids))
    out: dict[int, ExtendedStats] = {sid: ExtendedStats() for sid in candidate_song_ids}

    # 1. set-role counts in one query, with closer detection via set-max window.
    rows = conn.execute(
        f"""
        WITH set_maxes AS (
            SELECT show_id, set_number, MAX(position) AS max_pos
            FROM setlist_songs
            GROUP BY show_id, set_number
        )
        SELECT ss.song_id,
            SUM(CASE WHEN ss.set_number='1' AND ss.position=1 THEN 1 ELSE 0 END) AS set1_openers,
            SUM(CASE WHEN ss.set_number='2' AND ss.position=1 THEN 1 ELSE 0 END) AS set2_openers,
            SUM(CASE WHEN ss.set_number='E' THEN 1 ELSE 0 END) AS encores,
            SUM(CASE WHEN sm.max_pos = ss.position THEN 1 ELSE 0 END) AS closers,
            COUNT(*) AS total
        FROM setlist_songs ss
        JOIN shows s USING (show_id)
        JOIN set_maxes sm ON sm.show_id = ss.show_id AND sm.set_number = ss.set_number
        WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
        GROUP BY ss.song_id
        """,
        [*candidate_song_ids, show_date],
    ).fetchall()
    for r in rows:
        e = out[r["song_id"]]
        total = max(1, r["total"] or 1)
        e.set1_opener_rate = (r["set1_openers"] or 0) / total
        e.set2_opener_rate = (r["set2_openers"] or 0) / total
        e.encore_rate = (r["encores"] or 0) / total
        e.closer_score = (r["closers"] or 0) / total

    # 2. times_at_venue + derived venue_debut_affinity.
    if venue_id is not None:
        venue_counts = dict(
            conn.execute(
                f"""
                SELECT ss.song_id, COUNT(*) AS n
                FROM setlist_songs ss JOIN shows s USING (show_id)
                WHERE ss.song_id IN ({placeholders})
                  AND s.show_date < ? AND s.venue_id = ?
                GROUP BY ss.song_id
                """,
                [*candidate_song_ids, show_date, venue_id],
            ).fetchall()
        )
    else:
        venue_counts = {}
    total_counts = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(*) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
            GROUP BY ss.song_id
            """,
            [*candidate_song_ids, show_date],
        ).fetchall()
    )
    for sid in candidate_song_ids:
        n_v = venue_counts.get(sid, 0)
        n_total = total_counts.get(sid, 0)
        out[sid].times_at_venue = n_v
        out[sid].venue_debut_affinity = (n_v / n_total) if n_total > 0 else 0.0

    # 3. Song metadata (debut_year, is_cover) — one query over songs table.
    meta = conn.execute(
        f"SELECT song_id, debut_date, original_artist FROM songs WHERE song_id IN ({placeholders})",
        candidate_song_ids,
    ).fetchall()
    for r in meta:
        e = out[r["song_id"]]
        dd = r["debut_date"]
        if dd and len(dd) >= 4:
            try:
                e.debut_year = int(dd[:4])
            except ValueError:
                pass
        e.is_cover = 1 if r["original_artist"] else 0

    # 4a. Tour-opener / tour-closer rates. "Tour opener" = show with
    # tour_position=1; "tour closer" = show with tour_position = max for
    # that tour_id. Uses historical shows only (show_date < cutoff).
    tour_role_rows = conn.execute(
        f"""
        WITH tour_maxes AS (
            SELECT tour_id, MAX(tour_position) AS max_pos
            FROM shows WHERE tour_id IS NOT NULL GROUP BY tour_id
        )
        SELECT ss.song_id,
            -- Only count tour-openers/closers where the show belongs to a
            -- real tour (tour_id NOT NULL). One-off guest appearances have
            -- tour_id=NULL and would otherwise inflate these rates.
            SUM(CASE WHEN s.tour_id IS NOT NULL AND s.tour_position = 1
                     THEN 1 ELSE 0 END) AS tour_openers,
            SUM(CASE WHEN tm.max_pos IS NOT NULL AND s.tour_position = tm.max_pos
                     THEN 1 ELSE 0 END) AS tour_closers,
            COUNT(*) AS total
        FROM setlist_songs ss
        JOIN shows s USING (show_id)
        LEFT JOIN tour_maxes tm ON tm.tour_id = s.tour_id
        WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
        GROUP BY ss.song_id
        """,
        [*candidate_song_ids, show_date],
    ).fetchall()
    for r in tour_role_rows:
        e = out[r["song_id"]]
        total = max(1, r["total"] or 1)
        e.tour_opener_rate = (r["tour_openers"] or 0) / total
        e.tour_closer_rate = (r["tour_closers"] or 0) / total

    # 4. Days-since-last-played (calendar recency distinct from shows-since).
    last_rows = conn.execute(
        f"""
        SELECT ss.song_id, MAX(s.show_date) AS last_date
        FROM setlist_songs ss JOIN shows s USING (show_id)
        WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
        GROUP BY ss.song_id
        """,
        [*candidate_song_ids, show_date],
    ).fetchall()
    show_d = date.fromisoformat(show_date)
    for r in last_rows:
        last = r["last_date"]
        if last:
            out[r["song_id"]].days_since_last_played_anywhere = (
                show_d - date.fromisoformat(last)
            ).days

    return out


def compute_bustout_score(shows_since_last: int | None) -> float:
    """0.0 if never played or just played; ramps to 1.0 at `threshold` shows."""
    if shows_since_last is None:
        return 0.0
    return min(1.0, shows_since_last / BUSTOUT_THRESHOLD_SHOWS)
