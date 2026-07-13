"""Automated post-show close-out.

Nothing used to finalize a show: `finalize_scorecard` was only reachable from the
/recap page, so a scorecard was written lazily the first time a human looked at
it — and the score came from `live_songs`, which only holds what was hand-entered
plus whatever the in-process sync poller happened to reconcile while the app was
open. A night spent actually watching the band left a half-empty, unscored show.

This module reconciles the real setlist from phish.net and finalizes the
scorecard on its own.

**When is it safe?** phish.net exposes no "posted at" timestamp on a setlist row,
so we cannot ask whether one is final — only what it says right now. And there is
no structural end-of-show marker either: an encore is the obvious candidate, but
only ~96% of shows have one, so gating on it would hang forever on the rest.

So we detect *quiescence* instead of guessing a clock hour: poll the one show's
setlist and close out once it stops changing (identical across QUIET_POLLS
consecutive polls). An encore is a corroborating signal, not a gate. This is also
what makes the watcher timezone-agnostic — a west-coast show simply stays
unstable longer and closes out when its data lands, with no venue-timezone table.

See docs/plans/2026-07-13-automated-close-out.md.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from phishpicker.config import Settings
from phishpicker.db.connection import open_db
from phishpicker.live import create_live_show
from phishpicker.live_sync import sync_show_with_phishnet
from phishpicker.push import send_push
from phishpicker.scoring_service import finalize_scorecard
from phishpicker.scoring_store import ensure_frozen
from phishpicker.venue_tz import tz_for_state

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/New_York")

# Open the watch window late enough that the show can plausibly be over. Shows
# run to ~23:00 local; a west-coast one is still playing at this hour in ET, but
# that costs only a few no-op polls and stability detection sorts it out.
WATCH_FROM_HOUR = 22
WATCH_FROM_MINUTE = 30

# Consecutive identical polls that mean "the setlist has gone quiet". At the
# 10-minute cadence of the sidecar tick, 2 polls is ~20 minutes of no edits.
QUIET_POLLS = 2

Fingerprint = tuple[tuple[str, int, str], ...]


def setlist_fingerprint(net_rows: list[dict]) -> Fingerprint:
    """Order-independent identity of a setlist as phish.net currently reports it.

    Sorted because the API makes no ordering promise — an unsorted fingerprint
    would read as "changed" on every poll and never go quiet. The encore arrives
    as 'e' but is 'E' everywhere else in the codebase, so normalize case.
    """
    return tuple(
        sorted(
            (str(r["set"]).upper(), int(r["position"]), str(r["song"]))
            for r in net_rows
        )
    )


def has_encore(net_rows: list[dict]) -> bool:
    """True once an encore set has appeared. Corroborating only — see module doc."""
    return any(str(r["set"]).upper().startswith("E") for r in net_rows)


def should_close_out(history: list[Fingerprint]) -> bool:
    """True when the last QUIET_POLLS fingerprints are identical and non-empty.

    The non-empty guard matters: before anyone has typed the setlist in, every
    poll returns nothing, and "consistently nothing" would otherwise look like
    quiescence and finalize the show as a total miss.
    """
    if len(history) < QUIET_POLLS:
        return False
    recent = history[-QUIET_POLLS:]
    if not recent[0]:
        return False
    return all(fp == recent[0] for fp in recent)


def _window_opens_at(show_date: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(show_date).replace(
        hour=WATCH_FROM_HOUR, minute=WATCH_FROM_MINUTE, tzinfo=tz
    )


def watch_window_open(
    now: datetime, *, show_date: str, tz: ZoneInfo = TZ
) -> bool:
    """True from 22:30 *venue-local* on the show date onward.

    Venue-local, not Eastern: at 22:30 ET a Chula Vista show is mid-second-set,
    and polling a band that's still playing just burns calls. `tz` comes from
    venue_tz.tz_for_state; ET is the documented fallback.

    Stays open through the small hours — the 11am daily pass is the backstop.
    """
    return now.astimezone(tz) >= _window_opens_at(show_date, tz)


def time_since_window_opened(
    now: datetime, *, show_date: str, tz: ZoneInfo = TZ
) -> timedelta:
    """How long the watcher waited before firing. Logged at close-out so the real
    setlist-lag distribution can be measured and WATCH_FROM_HOUR tightened on
    evidence rather than a guess."""
    return now.astimezone(tz) - _window_opens_at(show_date, tz)


def summary_push_payload(card: dict, context: dict, *, venue: str) -> dict:
    """One push per closed-out show — never one per song.

    `live_sync` fires a push for every appended song when a VAPID key is passed;
    the close-out deliberately passes "" to suppress that (nobody wants the whole
    setlist pushed at 1am) and sends this single summary instead.
    """
    total = card["combined"]
    rank = context.get("rank_by_total")
    scored = context.get("shows_scored") or 0
    # is_best is trivially true on the first-ever scorecard. Claiming "your best
    # yet" out of a sample of one reads as a bug, so require something to beat.
    is_best = bool(context.get("is_best")) and scored > 1

    title = f"🏆 {total} pts — your best yet!" if is_best else f"🎸 {total} pts"
    if is_best:
        body = f"{venue} · best of {scored} shows"
    elif rank:
        body = f"{venue} · #{rank} of {scored} shows"
    else:
        body = venue
    return {
        "title": title,
        "body": body,
        # Stable per show: a re-score after a late phish.net correction replaces
        # the earlier notification rather than stacking a second one.
        "tag": f"phishpicker-closeout-{card['show_date']}",
        "data": {"url": f"/recap?show={card.get('show_id', '')}"},
    }


def show_on(read_conn: sqlite3.Connection, show_date: str) -> dict | None:
    """The canonical show scheduled for a date, with its venue tz. None if no show."""
    row = read_conn.execute(
        "SELECT s.show_id, s.show_date, s.venue_id, v.name AS venue, v.state "
        "FROM shows s LEFT JOIN venues v ON v.venue_id = s.venue_id "
        "WHERE s.show_date = ? LIMIT 1",
        (show_date,),
    ).fetchone()
    if row is None:
        return None
    return {
        "show_date": row["show_date"],
        "venue_id": row["venue_id"],
        "venue": row["venue"] or "",
        "tz": ZoneInfo(tz_for_state(row["state"])),
    }


def is_finalized(live_conn: sqlite3.Connection, show_id: str) -> bool:
    return (
        live_conn.execute(
            "SELECT 1 FROM scorecards WHERE show_id = ?", (show_id,)
        ).fetchone()
        is not None
    )


def freeze_show(settings: Settings, scorer, show_date: str) -> str | None:
    """Pre-show: ensure a live_show row exists for `show_date` and freeze its
    bracket. No-op when already frozen, so a night tracked by hand is untouched.

    Frozen *before* the downbeat on purpose. Every model feature cutoff is
    `show_date < ?`, so a bracket built after the show still couldn't see it —
    but "we froze our prediction the next morning" is indefensible the moment any
    of this is published. Freeze early and the claim is airtight.
    """
    with closing(open_db(settings.db_path, read_only=True)) as read:
        show = show_on(read, show_date)
        if show is None:
            return None
        with closing(open_db(settings.live_db_path)) as live:
            show_id = create_live_show(live, show_date, show["venue_id"])
            try:
                froze = ensure_frozen(read, live, show_id, scorer=scorer)
            except Exception:
                log.warning("bracket freeze failed for %s", show_date, exc_info=True)
                return show_id
    log.info(
        "close-out: %s bracket for %s (%s)",
        "froze" if froze else "bracket already frozen",
        show_date,
        show["venue"],
    )
    return show_id


def close_out_show(
    settings: Settings,
    scorer,
    show_date: str,
    *,
    now: datetime | None = None,
    notify: bool = True,
) -> dict | None:
    """Reconcile the real setlist from phish.net and finalize the scorecard.

    Safe to call repeatedly: create_live_show is idempotent by date,
    sync_show_with_phishnet is an idempotent reconcile, and finalize_scorecard is
    an upsert — so the 11am backstop re-scores a late phish.net correction
    cleanly. The summary push only fires on the *transition* to finalized, so a
    re-score doesn't re-notify.
    """
    with closing(open_db(settings.db_path, read_only=True)) as read:
        show = show_on(read, show_date)
    if show is None:
        return None

    with closing(open_db(settings.live_db_path)) as live:
        show_id = create_live_show(live, show_date, show["venue_id"])
        already = is_finalized(live, show_id)

    # scorer on => capture_snapshot per append, so LIVE points are credited just
    # as if sync had been left running all night. vapid_private_key="" => the
    # per-song push branch is skipped. Nobody wants 20 pushes at 1am.
    sync_show_with_phishnet(
        db_path=settings.db_path,
        live_db_path=settings.live_db_path,
        api_key=settings.phishnet_api_key,
        show_id=show_id,
        show_date=show_date,
        scorer=scorer,
        vapid_private_key="",
    )

    with closing(open_db(settings.db_path, read_only=True)) as read, closing(
        open_db(settings.live_db_path)
    ) as live:
        out = finalize_scorecard(read, live, show_id)
        card, context = out["scorecard"], out["context"]

        waited = time_since_window_opened(
            now or datetime.now(TZ), show_date=show_date, tz=show["tz"]
        )
        log.info(
            "close-out: finalized %s (%s) — %s pts, %.0f min after the window opened",
            show_date,
            show["venue"],
            card["combined"],
            waited.total_seconds() / 60,
        )

        if notify and not already:
            payload = summary_push_payload(
                {**card, "show_id": show_id}, context, venue=show["venue"]
            )
            try:
                send_push(
                    live,
                    payload,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_subject=settings.vapid_subject,
                )
            except Exception:
                log.warning("close-out summary push failed", exc_info=True)
    return out


# How far back the daily backstop looks for shows it never closed out (watcher
# missed it, container was down, phish.net was late). Bounded on purpose: the
# canonical DB holds ~2,250 shows going back to 1983, and an unbounded "close out
# every show without a scorecard" would try to reconcile the entire history of
# the band on first run.
BACKSTOP_DAYS = 3


def pending_close_outs(settings: Settings, now: datetime) -> list[dict]:
    """Recent shows (within BACKSTOP_DAYS) that have no scorecard yet."""
    today = now.astimezone(TZ).date()
    since = (today - timedelta(days=BACKSTOP_DAYS)).isoformat()
    with closing(open_db(settings.db_path, read_only=True)) as read:
        dates = [
            r["show_date"]
            for r in read.execute(
                "SELECT show_date FROM shows WHERE show_date >= ? AND show_date <= ? "
                "ORDER BY show_date",
                (since, today.isoformat()),
            ).fetchall()
        ]
        shows = [s for s in (show_on(read, d) for d in dates) if s]

    pending = []
    with closing(open_db(settings.live_db_path)) as live:
        for show in shows:
            row = live.execute(
                "SELECT show_id FROM live_show WHERE show_date = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (show["show_date"],),
            ).fetchone()
            if row and is_finalized(live, row["show_id"]):
                continue
            pending.append(show)
    return pending


def tick(settings: Settings, scorer, state: dict, now: datetime) -> list[str]:
    """One watcher tick. Polls each pending show and closes out the quiet ones.

    `state` maps show_date -> list of fingerprints seen so far; the caller owns it
    so it survives across ticks. Returns the show_dates closed out this tick.
    """
    from phishpicker.phishnet.client import PhishNetClient

    closed: list[str] = []
    for show in pending_close_outs(settings, now):
        date = show["show_date"]
        if not watch_window_open(now, show_date=date, tz=show["tz"]):
            continue
        try:
            with PhishNetClient(settings.phishnet_api_key) as client:
                rows = client.fetch_setlist_by_date(date)
        except Exception:
            log.warning("close-out: setlist poll failed for %s", date, exc_info=True)
            continue

        history = state.setdefault(date, [])
        history.append(setlist_fingerprint(rows))
        log.info(
            "close-out: polled %s — %d songs%s, %d/%d quiet",
            date,
            len(rows),
            " (encore in)" if has_encore(rows) else "",
            sum(1 for fp in history[-QUIET_POLLS:] if fp and fp == history[-1]),
            QUIET_POLLS,
        )
        if not should_close_out(history):
            continue
        try:
            close_out_show(settings, scorer, date, now=now)
            closed.append(date)
            state.pop(date, None)
        except Exception:
            log.exception("close-out: failed to finalize %s", date)
    return closed


def daily_pass(settings: Settings, scorer, now: datetime) -> dict:
    """Runs right after the 11am ingest.

    Backstop: close out any recent show the watcher never got to. Then freeze
    tonight's bracket — well before the downbeat, which is what makes the
    foresight claim defensible if any of this is ever published.
    """
    backstopped = []
    for show in pending_close_outs(settings, now):
        # Only shows already in the past; tonight's hasn't happened yet.
        if show["show_date"] >= now.astimezone(TZ).date().isoformat():
            continue
        try:
            if close_out_show(settings, scorer, show["show_date"], now=now):
                backstopped.append(show["show_date"])
                log.info("close-out: backstopped %s", show["show_date"])
        except Exception:
            log.exception("close-out: backstop failed for %s", show["show_date"])

    today = now.astimezone(TZ).date().isoformat()
    frozen = freeze_show(settings, scorer, today)
    return {"backstopped": backstopped, "frozen_today": frozen}
