import sqlite3

from phishpicker.model.rules import apply_post_rules
from phishpicker.model.scorer import HeuristicScorer, Scorer


def predict_next_stateless(
    *,
    read_conn: sqlite3.Connection,
    played_songs: list[int],
    current_set: str,
    show_date: str,
    venue_id: int | None,
    prev_trans_mark: str = ",",
    prev_set_number: str | None = None,
    top_n: int = 20,
    scorer: Scorer | None = None,
    song_ids_cache: list[int] | None = None,
    song_names_cache: dict[int, str] | None = None,
    stats_cache: dict | None = None,
    ext_cache: dict | None = None,
    bigram_cache: dict | None = None,
) -> list[dict]:
    """Pure prediction over an explicit played list — no live DB.

    The *_cache kwargs let a caller (notably the preview loop) precompute
    per-show artefacts once and reuse them across many slot calls.
    """
    if scorer is None:
        scorer = HeuristicScorer()

    if song_ids_cache is not None:
        song_ids = song_ids_cache
    else:
        song_ids = [
            r["song_id"] for r in read_conn.execute("SELECT song_id FROM songs").fetchall()
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
        stats_cache=stats_cache,
        ext_cache=ext_cache,
        bigram_cache=bigram_cache,
    )
    scored = apply_post_rules(scored, played_tonight=set(played_songs))
    scored = [(sid, s) for sid, s in scored if s > 0.0]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = scored[:top_n]
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
    and delegates to predict_next_stateless."""
    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (live_show_id,),
    ).fetchone()
    if not show:
        return []

    played = live_conn.execute(
        "SELECT song_id, entered_order, set_number, trans_mark FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (live_show_id,),
    ).fetchall()
    return predict_next_stateless(
        read_conn=read_conn,
        played_songs=[r["song_id"] for r in played],
        current_set=show["current_set"],
        show_date=show["show_date"],
        venue_id=show["venue_id"],
        prev_trans_mark=played[-1]["trans_mark"] if played else ",",
        prev_set_number=played[-1]["set_number"] if played else None,
        top_n=top_n,
        scorer=scorer,
    )
