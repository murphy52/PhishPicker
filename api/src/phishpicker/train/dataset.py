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
    # trans_mark of the song played immediately before this slot, if any.
    # Lets us populate segue_mark_in as a feature. "," for slot 1 (no prior
    # song) or when the prior slot had no segue mark recorded.
    prev_trans_mark: str = ","
    # set_number of the slot immediately before this one (None for slot 1 of
    # a show). Feeds is_first_in_set — "2" != "1" marks set-2-opener, etc.
    prev_set_number: str | None = None


def iter_training_groups(
    conn: sqlite3.Connection,
    cutoff_date: str,
    negatives_per_positive: int | None = 50,
    freq_negatives: int | None = None,
    uniform_negatives: int | None = None,
    seed: int = 0,
) -> Iterator[TrainingGroup]:
    """Yield one TrainingGroup per slot of every show strictly before cutoff_date.

    Two sampling modes:
    - Uniform only: pass `negatives_per_positive`; all negatives are uniform.
    - Stratified: pass `freq_negatives` + `uniform_negatives`; negatives are a
      concatenation of frequency-weighted + uniform samples (per carry-forward
      §1: frequency-only sampling skews the model toward popular songs).

    If both modes are supplied, stratified wins.
    """
    rng = random.Random(seed)
    all_song_ids = [r["song_id"] for r in conn.execute("SELECT song_id FROM songs")]

    if freq_negatives is not None or uniform_negatives is not None:
        fn = freq_negatives or 0
        un = uniform_negatives or 0
        stratified = True
        song_freq = dict(
            conn.execute(
                "SELECT song_id, COUNT(*) AS n FROM setlist_songs ss "
                "JOIN shows s USING (show_id) WHERE s.show_date < ? GROUP BY song_id",
                (cutoff_date,),
            ).fetchall()
        )
    else:
        fn = un = 0
        stratified = False
        song_freq = {}

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
            SELECT set_number, position, song_id, trans_mark
            FROM setlist_songs WHERE show_id = ?
            ORDER BY set_number, position
            """,
            (sh["show_id"],),
        ).fetchall()
        played: list[int] = []
        prev_trans_mark = ","
        prev_set_number: str | None = None
        for idx, row in enumerate(setlist, start=1):
            positive = int(row["song_id"])
            pool = [s for s in all_song_ids if s != positive and s not in played]

            if stratified:
                negatives = _stratified_sample(rng, pool, song_freq, fn, un)
            else:
                k = min(negatives_per_positive or 0, len(pool))
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
                prev_trans_mark=prev_trans_mark,
                prev_set_number=prev_set_number,
            )
            played.append(positive)
            # trans_mark on this row is the segue OUT of this song (into the
            # next slot). Preserve for the NEXT iteration's TrainingGroup.
            prev_trans_mark = row["trans_mark"] or ","
            prev_set_number = row["set_number"]


def _stratified_sample(
    rng: random.Random,
    pool: list[int],
    song_freq: dict[int, int],
    n_freq: int,
    n_uniform: int,
) -> tuple[int, ...]:
    if not pool:
        return ()
    picked: list[int] = []
    available = list(pool)

    # Frequency-weighted sampling without replacement.
    weights = [song_freq.get(s, 0) + 1 for s in available]  # +1 keeps rare songs drawable
    for _ in range(min(n_freq, len(available))):
        total = sum(weights)
        if total == 0:
            break
        r = rng.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if acc >= r:
                picked.append(available[i])
                available.pop(i)
                weights.pop(i)
                break

    # Uniform sampling from what's left.
    k = min(n_uniform, len(available))
    if k > 0:
        picked.extend(rng.sample(available, k))
    return tuple(picked)
