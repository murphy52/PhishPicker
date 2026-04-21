"""Second-batch feature computations for the LightGBM ranker.

Kept separate from `phishpicker.model.stats.compute_song_stats` because that
function is also consumed by the heuristic scorer and frozen SongStats dataclass.
Extended stats are LightGBM-only and live in a plain dict keyed by song_id.

Everything here is a pure function over (conn, show_date, venue_id,
candidate_song_ids) so the trainer can cache shared scans per-fold if
needed in a future optimization pass.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import date

# 50 shows turned out to be far too low for real Phish rotation — songs can
# go 30-40 shows between plays and still be core rotation. A proper bustout
# is typically 100+ shows (closer to 200 for the famous ones). Raised to 100.
BUSTOUT_THRESHOLD_SHOWS: int = 100

# Songs attributed to one of these artists are NOT covers. phish.net stores
# Phish originals as 'Phish' (not NULL) and many TAB-originated songs that
# joined the Phish rotation as 'Trey Anastasio'. Other band members appear
# similarly. Anyone NOT in this set (and not NULL) is a real third-party
# cover.
PHISH_FAMILY_ARTISTS: frozenset[str] = frozenset({
    "Phish",
    "Trey Anastasio",
    "Mike Gordon",
    "Page McConnell",
    "Jon Fishman",
})


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
    times_this_tour: int = 0
    shows_since_last_played_this_tour: int = -1
    shows_since_last_set1_opener: int = -1
    shows_since_last_any_opener_role: int = -1
    avg_set_position_when_played: float = -1.0
    days_since_debut: int = -1
    plays_last_6mo: int = 0
    recent_play_acceleration: float = 0.0


def compute_extended_stats(
    conn: sqlite3.Connection,
    show_date: str,
    venue_id: int | None,
    candidate_song_ids: list[int],
    tour_id: int | None = None,
    all_show_dates: list[str] | None = None,
) -> dict[int, ExtendedStats]:
    """Return {song_id: ExtendedStats} for the candidates as of show_date.

    `tour_id` scopes the tour-rotation features (times_this_tour,
    shows_since_last_played_this_tour). If None, those fields keep their
    sentinel defaults — live shows that can't resolve a tour_id just see
    zeros.
    """
    if not candidate_song_ids:
        return {}

    placeholders = ",".join("?" * len(candidate_song_ids))
    out: dict[int, ExtendedStats] = {sid: ExtendedStats() for sid in candidate_song_ids}

    # ONE big aggregate query covering every per-song feature that's a counts-
    # or max-over-setlist_songs-joined-shows. This is the hot path during
    # training: called ~65k times per walk-forward refit. Earlier iteration
    # ran 5-7 separate queries that each rescanned the same join → cut the
    # hot path by ~3x by fusing them.
    #
    # NULL-safe: venue_id and tour_id may be None. SQLite's `=` on NULL
    # returns NULL (falsy under SUM CASE), which is exactly what we want —
    # no special-casing needed.
    rows = conn.execute(
        f"""
        WITH set_maxes AS (
            SELECT show_id, set_number, MAX(position) AS max_pos, MIN(position) AS min_pos
            FROM setlist_songs GROUP BY show_id, set_number
        ),
        tour_maxes AS (
            SELECT tour_id, MAX(tour_position) AS max_pos
            FROM shows WHERE tour_id IS NOT NULL GROUP BY tour_id
        )
        SELECT ss.song_id,
            COUNT(*) AS total,
            SUM(CASE WHEN ss.set_number='1' AND ss.position=1 THEN 1 ELSE 0 END) AS set1_openers,
            SUM(CASE WHEN ss.set_number='2' AND ss.position=1 THEN 1 ELSE 0 END) AS set2_openers,
            SUM(CASE WHEN ss.set_number='E' THEN 1 ELSE 0 END) AS encores,
            SUM(CASE WHEN sm.max_pos = ss.position THEN 1 ELSE 0 END) AS closers,
            SUM(CASE WHEN s.tour_id IS NOT NULL AND s.tour_position = 1
                     THEN 1 ELSE 0 END) AS tour_openers,
            SUM(CASE WHEN tm.max_pos IS NOT NULL AND s.tour_position = tm.max_pos
                     THEN 1 ELSE 0 END) AS tour_closers,
            SUM(CASE WHEN s.venue_id = ? THEN 1 ELSE 0 END) AS venue_plays,
            SUM(CASE WHEN s.tour_id = ? THEN 1 ELSE 0 END) AS times_this_tour_n,
            MAX(s.show_date) AS last_date,
            MAX(CASE WHEN s.tour_id = ? THEN s.show_date END) AS last_in_tour_date,
            -- A: last time this song was the set-1 opener specifically.
            MAX(CASE WHEN ss.set_number='1' AND ss.position=1
                     THEN s.show_date END) AS last_set1_opener_date,
            -- B: last time it held ANY opener role — first song of any set, or the encore.
            MAX(CASE WHEN ss.position = sm.min_pos
                     THEN s.show_date END) AS last_any_opener_date,
            -- C: mean show-global position across all plays (warm-up vs jam-vehicle proxy).
            AVG(ss.position) AS avg_position
        FROM setlist_songs ss
        JOIN shows s USING (show_id)
        JOIN set_maxes sm ON sm.show_id = ss.show_id AND sm.set_number = ss.set_number
        LEFT JOIN tour_maxes tm ON tm.tour_id = s.tour_id
        WHERE ss.song_id IN ({placeholders}) AND s.show_date < ?
        GROUP BY ss.song_id
        """,
        [venue_id, tour_id, tour_id, *candidate_song_ids, show_date],
    ).fetchall()

    show_d = date.fromisoformat(show_date)

    # Precompute sorted show_dates for shows-since-X bisect lookups. Caller
    # can pass this in to amortize across many build_feature_rows calls.
    if all_show_dates is None:
        all_show_dates = sorted(r[0] for r in conn.execute("SELECT show_date FROM shows"))
    import bisect as _bisect

    show_idx = _bisect.bisect_left(all_show_dates, show_date)

    def _shows_since(last_d: str | None) -> int:
        if not last_d:
            return -1
        left = _bisect.bisect_right(all_show_dates, last_d)
        return max(0, show_idx - left)

    for r in rows:
        e = out[r["song_id"]]
        total = max(1, r["total"] or 1)
        e.set1_opener_rate = (r["set1_openers"] or 0) / total
        e.set2_opener_rate = (r["set2_openers"] or 0) / total
        e.encore_rate = (r["encores"] or 0) / total
        e.closer_score = (r["closers"] or 0) / total
        e.tour_opener_rate = (r["tour_openers"] or 0) / total
        e.tour_closer_rate = (r["tour_closers"] or 0) / total
        e.times_at_venue = r["venue_plays"] or 0
        e.venue_debut_affinity = (r["venue_plays"] or 0) / total
        if tour_id is not None:
            e.times_this_tour = r["times_this_tour_n"] or 0
        last = r["last_date"]
        if last:
            e.days_since_last_played_anywhere = (show_d - date.fromisoformat(last)).days
        # New A/B/C.
        e.shows_since_last_set1_opener = _shows_since(r["last_set1_opener_date"])
        e.shows_since_last_any_opener_role = _shows_since(r["last_any_opener_date"])
        avg_pos = r["avg_position"]
        if avg_pos is not None:
            e.avg_set_position_when_played = float(avg_pos)

    # For shows_since_last_played_this_tour we need the SHOWS count between
    # the song's last in-tour play and the cutoff — not a row count. Bisect
    # over the tour's show_date list is the cheapest way.
    if tour_id is not None:
        tour_show_dates = sorted(
            r[0]
            for r in conn.execute(
                "SELECT show_date FROM shows WHERE tour_id = ? AND show_date < ?",
                (tour_id, show_date),
            )
        )
        cutoff_idx = len(tour_show_dates)
        for r in rows:
            last_in_tour = r["last_in_tour_date"]
            if last_in_tour:
                left = _bisect.bisect_right(tour_show_dates, last_in_tour)
                out[r["song_id"]].shows_since_last_played_this_tour = max(0, cutoff_idx - left)

    # Song metadata lives on a different table (songs) — one extra lightweight
    # query. Small enough to leave separate.
    meta = conn.execute(
        f"SELECT song_id, debut_date, original_artist FROM songs WHERE song_id IN ({placeholders})",
        candidate_song_ids,
    ).fetchall()
    for r in meta:
        e = out[r["song_id"]]
        dd = r["debut_date"]
        if dd and len(dd) >= 4:
            with contextlib.suppress(ValueError):
                e.debut_year = int(dd[:4])
            # B1: days_since_debut — per-song "how new is this song in the
            # repertoire" signal. Proxy for album-recency when album data
            # is unavailable.
            with contextlib.suppress(ValueError):
                e.days_since_debut = max(0, (show_d - date.fromisoformat(dd)).days)
        # is_cover: phish.net stores original_artist='Phish' for Phish
        # originals (NOT NULL — only ~20 of 983 songs have NULL, mostly
        # one-off jams with unknown attribution). And many TAB songs that
        # entered the Phish rotation are stored as 'Trey Anastasio'. Both
        # of those are family — not covers. Pre-v8 the check was simply
        # `if original_artist`, which inverted the feature: Phish originals
        # got is_cover=1 and the model couldn't distinguish anything
        # meaningful. Use a Phish-family whitelist instead.
        artist = r["original_artist"]
        e.is_cover = 1 if (artist is not None and artist not in PHISH_FAMILY_ARTISTS) else 0

    # B2: plays_last_6mo + recent_play_acceleration. Momentum signal —
    # songs that got hot in the last six months. Picks up Evolve-style
    # album-release spikes without needing explicit album data.
    plays_6mo = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(*) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders})
              AND s.show_date < ?
              AND s.show_date >= date(?, '-6 months')
            GROUP BY ss.song_id
            """,
            [*candidate_song_ids, show_date, show_date],
        ).fetchall()
    )
    plays_12mo = dict(
        conn.execute(
            f"""
            SELECT ss.song_id, COUNT(*) AS n
            FROM setlist_songs ss JOIN shows s USING (show_id)
            WHERE ss.song_id IN ({placeholders})
              AND s.show_date < ?
              AND s.show_date >= date(?, '-1 year')
            GROUP BY ss.song_id
            """,
            [*candidate_song_ids, show_date, show_date],
        ).fetchall()
    )
    for sid in candidate_song_ids:
        recent = plays_6mo.get(sid, 0)
        prior = plays_12mo.get(sid, 0) - recent  # plays in 6-12 month window
        out[sid].plays_last_6mo = recent
        # Symmetric ratio, bounded. When prior=0 and recent>0, treat as strong
        # acceleration (new song); divide-by-zero avoidance.
        if prior == 0:
            out[sid].recent_play_acceleration = 2.0 if recent > 0 else 0.0
        else:
            out[sid].recent_play_acceleration = recent / prior

    return out


def compute_bustout_score(shows_since_last: int | None) -> float:
    """0.0 if never played or just played; ramps to 1.0 at `threshold` shows."""
    if shows_since_last is None:
        return 0.0
    return min(1.0, shows_since_last / BUSTOUT_THRESHOLD_SHOWS)
