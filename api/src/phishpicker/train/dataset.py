"""Training group generator.

One group per (show_id, slot_number) = one ranking question. Each group holds
the positive (actually-played) song plus a sample of negatives, which the
LambdaRank objective will push down below the positive.
"""

import random
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingGroup:
    show_id: int
    show_date: str
    venue_id: int | None
    slot_number: int
    current_set: str
    played_before_slot: tuple[int, ...]
    positive_song_id: int
    negative_song_ids: tuple[int, ...]


def iter_training_groups(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int = 50,
    seed: int = 0,
) -> Iterator[TrainingGroup]:
    """Yield one TrainingGroup per slot of every show strictly before cutoff_date.

    Negatives are sampled uniformly from songs not yet played in that show.
    """
    rng = random.Random(seed)
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]
    shows = conn.execute(
        """
        SELECT show_id, show_date, venue_id
        FROM shows
        WHERE show_date < ?
        ORDER BY show_date, show_id
        """,
        (cutoff_date,),
    ).fetchall()
    for sh in shows:
        setlist = conn.execute(
            """
            SELECT set_number, position, song_id
            FROM setlist_songs WHERE show_id = ?
            ORDER BY set_number, position
            """,
            (sh["show_id"],),
        ).fetchall()
        played: list[int] = []
        for idx, row in enumerate(setlist, start=1):
            positive = int(row["song_id"])
            pool = [s for s in all_song_ids if s != positive and s not in played]
            k = min(negatives_per_positive, len(pool))
            negatives = tuple(rng.sample(pool, k)) if k > 0 else ()
            yield TrainingGroup(
                show_id=int(sh["show_id"]),
                show_date=sh["show_date"],
                venue_id=sh["venue_id"],
                slot_number=idx,
                current_set=row["set_number"],
                played_before_slot=tuple(played),
                positive_song_id=positive,
                negative_song_ids=negatives,
            )
            played.append(positive)
