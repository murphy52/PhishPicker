"""Show-level *inclusion* features: P(song appears anywhere in a show).

A separate model from the slot-level next-song ranker. It deliberately drops
every transition/slot feature (bigram, prev-song, set position) — at the show
level a song either appears or not, regardless of adjacency — and keeps the
song-intrinsic frequency/recency/newness signals. See
`docs/spike-show-level-inclusion-model.md` for the rationale and spike results.

Leakage rule: every feature for a show on date D uses only plays strictly
before D. The same builder serves training (iterate historical shows) and
inference (one upcoming show), so train/serve features are computed by
identical code.
"""

from __future__ import annotations

import bisect
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

from phishpicker.train.albums import latest_album_as_of, song_album_map

# Phish-family artists — mirrors extended_stats.PHISH_FAMILY_ARTISTS intent:
# family-written songs are originals, not covers.
PHISH_FAMILY_ARTISTS = frozenset(
    {"Phish", "Trey Anastasio", "Mike Gordon", "Page McConnell",
     "Jon Fishman", "Ghosts of the Forest"}
)

# "Road-testing" window: a brand-new original still in its debut run.
NEW_WINDOW_DAYS = 180
# Candidate universe: songs with >=1 play in the trailing N years (live rotation).
UNIVERSE_YEARS = 3

INCLUSION_FEATURE_COLUMNS: list[str] = [
    "total_plays_ever",
    "plays_last_12mo",
    "plays_last_6mo",
    "recent_play_acceleration",
    "days_since_last_played",
    "shows_since_last_played",
    "days_since_debut",
    "is_cover",
    "is_from_latest_album",
    "days_since_last_new_album",
    "times_this_tour",
    "times_at_venue",
    "new_original_flag",
    "run_position",
    "run_length",
    "tour_position",
    "month",
    "dow",
    "is_tour_opener",
]

# A large sentinel for "never happened" gaps (days / shows since last).
_MISSING = 99999


@dataclass(frozen=True)
class ShowContext:
    """Everything known about a show *before* it happens."""

    show_date: date
    venue_id: int | None
    tour_id: int | None
    run_position: int
    run_length: int
    tour_position: int
    seq: int  # index of the show in chronological order (for shows-since gaps)


class InclusionHistory:
    """Loads play history once; emits leak-free features for any show context."""

    def __init__(self, conn: sqlite3.Connection):
        conn.row_factory = sqlite3.Row
        self._conn = conn
        shows = conn.execute(
            "SELECT show_id, show_date, venue_id, tour_id, run_position, "
            "run_length, tour_position FROM shows ORDER BY show_date, show_id"
        ).fetchall()
        self.shows = shows
        self.seq_of: dict[int, int] = {}
        self._ctx_by_show: dict[int, ShowContext] = {}
        for i, sh in enumerate(shows):
            self.seq_of[sh["show_id"]] = i
            self._ctx_by_show[sh["show_id"]] = ShowContext(
                show_date=date.fromisoformat(sh["show_date"]),
                venue_id=sh["venue_id"],
                tour_id=sh["tour_id"],
                run_position=sh["run_position"] or 0,
                run_length=sh["run_length"] or 0,
                tour_position=sh["tour_position"] or 0,
                seq=i,
            )

        # song -> chronologically sorted play events (before dedup by show)
        self.plays: dict[int, list[dict]] = defaultdict(list)
        self.played_in_show: dict[int, set[int]] = defaultdict(set)
        for a in conn.execute("SELECT DISTINCT show_id, song_id FROM setlist_songs"):
            ctx = self._ctx_by_show.get(a["show_id"])
            if ctx is None:
                continue
            self.played_in_show[a["show_id"]].add(a["song_id"])
            self.plays[a["song_id"]].append(
                {
                    "ord": ctx.show_date.toordinal(),
                    "seq": ctx.seq,
                    "tour": ctx.tour_id,
                    "venue": ctx.venue_id,
                }
            )
        for sid in self.plays:
            self.plays[sid].sort(key=lambda m: m["ord"])
        self._ords: dict[int, list[int]] = {
            sid: [m["ord"] for m in ms] for sid, ms in self.plays.items()
        }

        # song metadata
        self.debut: dict[int, date | None] = {}
        self.is_cover: dict[int, int] = {}
        for s in conn.execute("SELECT song_id, debut_date, original_artist FROM songs"):
            dd = s["debut_date"]
            self.debut[s["song_id"]] = (
                date.fromisoformat(dd) if dd and len(dd) >= 10 else None
            )
            art = s["original_artist"]
            self.is_cover[s["song_id"]] = (
                1 if (art is not None and art not in PHISH_FAMILY_ARTISTS) else 0
            )
        self._album_map = song_album_map(conn, list(self.plays.keys()))

    def context_for(self, show_id: int) -> ShowContext:
        return self._ctx_by_show[show_id]

    def _count_between(self, sid: int, lo_ord: int, hi_ord: int) -> int:
        arr = self._ords.get(sid)
        if not arr:
            return 0
        return bisect.bisect_left(arr, hi_ord) - bisect.bisect_left(arr, lo_ord)

    def candidate_ids(self, show_date: date) -> list[int]:
        """Songs with >=1 play in the trailing window, strictly before the show."""
        hi = show_date.toordinal()
        lo = hi - UNIVERSE_YEARS * 365
        return [sid for sid in self.plays if self._count_between(sid, lo, hi) > 0]

    def feature_row(self, sid: int, ctx: ShowContext) -> list[float] | None:
        """Leak-free feature vector for (song, show), or None if no prior history."""
        arr = self._ords.get(sid)
        if not arr:
            return None
        d_ord = ctx.show_date.toordinal()
        hi = bisect.bisect_left(arr, d_ord)  # plays strictly before the show
        if hi == 0:
            return None  # never played before -> nothing to score (true debut)

        total = hi
        p12 = self._count_between(sid, d_ord - 365, d_ord)
        p6 = self._count_between(sid, d_ord - 182, d_ord)
        p6_prev = self._count_between(sid, d_ord - 365, d_ord - 182)
        last = self.plays[sid][hi - 1]
        days_since_last = d_ord - last["ord"]
        shows_since_last = ctx.seq - last["seq"]

        dd = self.debut.get(sid)
        days_since_debut = (d_ord - dd.toordinal()) if dd else _MISSING
        cov = self.is_cover.get(sid, 0)

        prior = self.plays[sid][:hi]
        times_this_tour = sum(1 for m in prior if m["tour"] == ctx.tour_id)
        times_at_venue = sum(1 for m in prior if m["venue"] == ctx.venue_id)

        la = latest_album_as_of(ctx.show_date.isoformat())
        song_alb = self._album_map.get(sid)
        is_latest = 1 if (song_alb and la and song_alb.album_id == la.album_id) else 0
        days_since_new_album = (
            d_ord - date.fromisoformat(la.release_date).toordinal() if la else _MISSING
        )
        new_original_flag = (
            1 if (cov == 0 and days_since_debut <= NEW_WINDOW_DAYS and is_latest == 0) else 0
        )
        is_tour_opener = 1 if ctx.tour_position == 1 else 0

        return [
            float(total),
            float(p12),
            float(p6),
            float(p6 - p6_prev),
            float(days_since_last),
            float(shows_since_last),
            float(days_since_debut),
            float(cov),
            float(is_latest),
            float(days_since_new_album),
            float(times_this_tour),
            float(times_at_venue),
            float(new_original_flag),
            float(ctx.run_position),
            float(ctx.run_length),
            float(ctx.tour_position),
            float(ctx.show_date.month),
            float(ctx.show_date.weekday()),
            float(is_tour_opener),
        ]

    def feature_matrix(
        self, ctx: ShowContext, sids: list[int]
    ) -> tuple[np.ndarray, list[int]]:
        """(matrix, sids_kept) for a single show — used at inference time."""
        rows, kept = [], []
        for sid in sids:
            r = self.feature_row(sid, ctx)
            if r is not None:
                rows.append(r)
                kept.append(sid)
        if not rows:
            return np.empty((0, len(INCLUSION_FEATURE_COLUMNS))), []
        return np.array(rows, dtype=float), kept


def build_training_data(
    conn: sqlite3.Connection, warmup_shows: int = 50
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Full historical (X, y, show_ordinal_dates, show_ids) for training/holdout."""
    hist = InclusionHistory(conn)
    X, y, dates, show_ids = [], [], [], []
    for i, sh in enumerate(hist.shows):
        if i < warmup_shows:
            continue
        actual = hist.played_in_show[sh["show_id"]]
        if not actual:
            continue  # future/announced show with no setlist yet — nothing to learn
        ctx = hist.context_for(sh["show_id"])
        for sid in hist.candidate_ids(ctx.show_date):
            row = hist.feature_row(sid, ctx)
            if row is None:
                continue
            X.append(row)
            y.append(1 if sid in actual else 0)
            dates.append(ctx.show_date.toordinal())
            show_ids.append(sh["show_id"])
    return (
        np.array(X, dtype=float),
        np.array(y, dtype=int),
        np.array(dates, dtype=int),
        np.array(show_ids, dtype=int),
    )
