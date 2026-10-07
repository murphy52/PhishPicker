import math
import sqlite3

from phishpicker.model.rules import apply_post_rules
from phishpicker.model.scorer import HeuristicScorer, Scorer

# Softmax temperature for full_list probabilities. Chosen so the mean top-1
# probability matches the share-of-positive-sum lists it replaced (0.120 over
# 28 shows, Oct 2026 spike).
FULL_LIST_SOFTMAX_T = 1.248


def predict_next_stateless(
    *,
    read_conn: sqlite3.Connection,
    played_songs: list[int],
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str = ",",
    prev_set_number: str | None = None,
    slots_into_current_set: int = 1,
    top_n: int = 20,
    scorer: Scorer | None = None,
    song_ids_cache: list[int] | None = None,
    song_names_cache: dict[int, str] | None = None,
    stats_cache: dict | None = None,
    ext_cache: dict | None = None,
    bigram_cache: dict | None = None,
    played_in_run: set[int] | None = None,
    full_list: bool = False,
) -> list[dict]:
    """Pure prediction over an explicit played list — no live DB.

    The *_cache kwargs let a caller (notably the preview loop) precompute
    per-show artefacts once and reuse them across many slot calls.

    By default only positive raw scores are candidates, each priced as its
    share of the top_n's sum. full_list (the phishvs bundle) instead keeps the
    top_n by raw score whatever its sign, priced by softmax(score / T).
    """
    if scorer is None:
        scorer = HeuristicScorer()

    if song_ids_cache is not None:
        song_ids = song_ids_cache
    else:
        song_ids = [
            r["song_id"]
            for r in read_conn.execute(
                "SELECT song_id FROM songs ORDER BY song_id"
            ).fetchall()
        ]
    if not song_ids:
        return []

    scored = scorer.score_candidates(
        conn=read_conn,
        show_date=show_date,
        venue_id=venue_id,
        played_songs=played_songs,
        current_set=current_set,
        candidate_song_ids=song_ids,
        prev_trans_mark=prev_trans_mark,
        prev_set_number=prev_set_number,
        slots_into_current_set=slots_into_current_set,
        stats_cache=stats_cache,
        ext_cache=ext_cache,
        bigram_cache=bigram_cache,
    )
    if full_list:
        # apply_post_rules zeroes excluded songs, which only hides them behind
        # the > 0 filter; with negatives kept they must be removed outright.
        # Non-finite scores go too, as the > 0 filter drops NaN.
        excluded = set(played_songs) | (played_in_run or set())
        scored = [(sid, s) for sid, s in scored if sid not in excluded and math.isfinite(s)]
    else:
        scored = apply_post_rules(
            scored, played_tonight=set(played_songs), played_in_run=played_in_run
        )
        scored = [(sid, s) for sid, s in scored if s > 0.0]
    # Deterministic tiebreak: score desc, then song_id asc — the live
    # next-song call must not flip between identical recomputes.
    scored.sort(key=lambda x: (-x[1], x[0]))

    top = scored[:top_n]
    if full_list:
        # Subtract the max before exponentiating, for numerical stability.
        hi = top[0][1] if top else 0.0
        weights = [math.exp((s - hi) / FULL_LIST_SOFTMAX_T) for _, s in top]
        total = sum(weights)
        normalized = [(sid, s, w / total) for (sid, s), w in zip(top, weights, strict=True)]
    else:
        total = sum(s for _, s in top) or 1.0
        normalized = [(sid, s, s / total) for sid, s in top]

    top_ids = [sid for sid, _, _ in normalized]
    if song_names_cache is not None:
        names = song_names_cache
    else:
        names = (
            dict(
                read_conn.execute(
                    f"SELECT song_id, name FROM songs WHERE song_id IN ({','.join('?' * len(top_ids))})",
                    top_ids,
                ).fetchall()
            )
            if top_ids
            else {}
        )
    return [
        {"song_id": sid, "name": names.get(sid, f"#{sid}"), "score": s, "probability": p}
        for sid, s, p in normalized
    ]


def predict_next(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    live_show_id: str,
    top_n: int = 20,
    scorer: Scorer | None = None,
) -> list[dict]:
    """Predict the next song for a live show. Loads played from the live DB
    and delegates to predict_next_stateless, with the same venue backfill and
    run filter as the bracket (live_preview.build_preview)."""
    # live_preview imports this module, so import from it at call time.
    from phishpicker.live_preview import _played_in_run, resolve_venue_id

    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (live_show_id,),
    ).fetchone()
    if not show:
        return []
    venue_id = resolve_venue_id(read_conn, show["show_date"], show["venue_id"])

    played = live_conn.execute(
        "SELECT song_id, entered_order, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (live_show_id,),
    ).fetchall()
    # 1-indexed position within the current set: one past the number of
    # already-played songs whose set_number matches the show's current set.
    slots_into_current_set = (
        sum(1 for r in played if r["set_number"] == show["current_set"]) + 1
    )
    return predict_next_stateless(
        read_conn=read_conn,
        played_songs=[r["song_id"] for r in played],
        current_set=show["current_set"],
        show_date=show["show_date"],
        venue_id=venue_id,
        prev_trans_mark=played[-1]["trans_mark"] if played else ",",
        prev_set_number=played[-1]["set_number"] if played else None,
        slots_into_current_set=slots_into_current_set,
        top_n=top_n,
        scorer=scorer,
        played_in_run=_played_in_run(read_conn, live_conn, show["show_date"], venue_id),
    )
