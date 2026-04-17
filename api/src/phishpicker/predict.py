import sqlite3

from phishpicker.model.heuristic import Context, score
from phishpicker.model.rules import apply_post_rules
from phishpicker.model.stats import compute_song_stats


def predict_next(
    read_conn: sqlite3.Connection,
    live_conn: sqlite3.Connection,
    live_show_id: str,
    top_n: int = 20,
) -> list[dict]:
    show = live_conn.execute(
        "SELECT show_date, venue_id, current_set FROM live_show WHERE show_id = ?",
        (live_show_id,),
    ).fetchone()
    if not show:
        return []

    played = live_conn.execute(
        "SELECT song_id, entered_order, set_number FROM live_songs "
        "WHERE show_id = ? ORDER BY entered_order",
        (live_show_id,),
    ).fetchall()
    played_ids = {r["song_id"] for r in played}
    position = sum(1 for r in played if r["set_number"] == show["current_set"]) + 1

    song_ids = [r["song_id"] for r in read_conn.execute("SELECT song_id FROM songs").fetchall()]
    if not song_ids:
        return []

    stats = compute_song_stats(
        read_conn, show_date=show["show_date"], venue_id=show["venue_id"], song_ids=song_ids
    )
    ctx = Context(current_set=show["current_set"], current_position=position)

    scored = [(sid, score(stats[sid], ctx)) for sid in song_ids]
    scored = apply_post_rules(scored, played_tonight=played_ids)
    # Filter out zero-score candidates — they are not viable predictions.
    scored = [(sid, s) for sid, s in scored if s > 0.0]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Rank-based display percentage over the visible top-N.
    # (No softmax — raw scores span orders of magnitude and would be
    # either uniform or spiky; not useful as "probability" in the UI.)
    top = scored[:top_n]
    total = sum(s for _, s in top) or 1.0
    normalized = [(sid, s, s / total) for sid, s in top]

    top_ids = [sid for sid, _, _ in normalized]
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
