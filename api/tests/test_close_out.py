from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from phishpicker.close_out import (
    QUIET_POLLS,
    TZ,
    WATCH_FROM_HOUR,
    has_encore,
    setlist_fingerprint,
    should_close_out,
    summary_push_payload,
    watch_window_open,
)


def _rows(*specs):
    """specs are (set, position, song) triples as phish.net returns them."""
    return [{"set": s, "position": p, "song": n} for s, p, n in specs]


SET1 = _rows(("1", 1, "AC/DC Bag"), ("1", 2, "Reba"))
SET1_PLUS = _rows(("1", 1, "AC/DC Bag"), ("1", 2, "Reba"), ("2", 1, "Tweezer"))
FULL = _rows(("1", 1, "AC/DC Bag"), ("2", 1, "Tweezer"), ("e", 1, "Tweezer Reprise"))


# --- fingerprint ---


def test_fingerprint_is_stable_across_row_order():
    """phish.net doesn't promise row order; the same setlist must fingerprint
    identically however it arrives, or every poll looks like a change."""
    assert setlist_fingerprint(SET1) == setlist_fingerprint(list(reversed(SET1)))


def test_fingerprint_changes_when_a_song_is_appended():
    assert setlist_fingerprint(SET1) != setlist_fingerprint(SET1_PLUS)


def test_fingerprint_changes_when_a_song_is_corrected():
    corrected = _rows(("1", 1, "AC/DC Bag"), ("1", 2, "Bathtub Gin"))
    assert setlist_fingerprint(SET1) != setlist_fingerprint(corrected)


def test_fingerprint_normalizes_set_case():
    """The encore arrives as 'e' from the API but 'E' elsewhere in the codebase."""
    assert setlist_fingerprint(_rows(("e", 1, "Wilson"))) == setlist_fingerprint(
        _rows(("E", 1, "Wilson"))
    )


def test_fingerprint_of_empty_setlist_is_falsy():
    assert not setlist_fingerprint([])


# --- encore detection (a corroborating signal, not a gate) ---


def test_has_encore_detects_lowercase_e():
    assert has_encore(FULL)


def test_has_encore_false_before_the_encore():
    assert not has_encore(SET1_PLUS)


# --- the close-out decision ---


def test_does_not_close_out_on_an_empty_setlist():
    """Nothing posted yet. Two empty polls are 'stable' but must never finalize —
    that would score the show as a total miss."""
    history = [setlist_fingerprint([])] * QUIET_POLLS
    assert not should_close_out(history)


def test_does_not_close_out_while_the_setlist_is_still_growing():
    history = [setlist_fingerprint(SET1), setlist_fingerprint(SET1_PLUS)]
    assert not should_close_out(history)


def test_does_not_close_out_on_a_single_poll():
    """One sighting is not quiescence — the very first poll of a show that is
    still being typed in would otherwise finalize a partial setlist."""
    assert not should_close_out([setlist_fingerprint(FULL)])


def test_closes_out_once_the_setlist_goes_quiet():
    history = [setlist_fingerprint(FULL)] * QUIET_POLLS
    assert should_close_out(history)


def test_closes_out_an_encoreless_show_on_stability_alone():
    """~4% of shows have no encore. Gating on the encore would hang forever."""
    history = [setlist_fingerprint(SET1_PLUS)] * QUIET_POLLS
    assert should_close_out(history)


def test_only_the_most_recent_polls_count():
    """An early edit must not poison the decision once the setlist settles."""
    history = [
        setlist_fingerprint(SET1),
        setlist_fingerprint(SET1_PLUS),
        *([setlist_fingerprint(FULL)] * QUIET_POLLS),
    ]
    assert should_close_out(history)


# --- watch window ---


@pytest.mark.parametrize(
    "day,hour,expected",
    [
        (14, 20, False),  # 8pm ET — band is on stage
        (14, 22, False),  # 10pm ET — still before the 22:30 open
        (14, 23, True),   # 11pm ET — east-coast show is over
        (15, 2, True),    # 2am ET — a west-coast setlist can land this late
        (15, 10, True),   # still open right up to the 11am backstop
    ],
)
def test_watch_window_opens_at_night_and_stays_open(day, hour, expected):
    """Opens at 22:30 ET on the show date and stays open through the small hours."""
    now = datetime(2026, 7, day, hour, 0, tzinfo=TZ)
    assert watch_window_open(now, show_date="2026-07-14") is expected


def test_watch_window_shut_before_the_show():
    now = datetime(2026, 7, 14, 14, 0, tzinfo=TZ)  # doors not even open
    assert watch_window_open(now, show_date="2026-07-14") is False


def test_watch_window_accepts_a_utc_now():
    """The sidecar ticks on UTC; the window is defined in local time. 03:00 UTC on
    the 15th is 23:00 EDT on the 14th — inside the window, not a day late."""
    assert watch_window_open(
        datetime(2026, 7, 15, 3, 0, tzinfo=UTC), show_date="2026-07-14"
    )


def test_watch_window_is_venue_local_not_eastern():
    """A west-coast show is mid-second-set at 22:30 ET. Opening the window on ET
    would poll a band that's still playing; the window must follow the venue."""
    pacific = ZoneInfo("America/Los_Angeles")
    # 23:00 ET on the show date == 20:00 PT — Phish is on stage in Chula Vista.
    during_show = datetime(2026, 7, 14, 23, 0, tzinfo=TZ)
    assert watch_window_open(during_show, show_date="2026-07-14", tz=pacific) is False
    # 23:00 PT — now it's over out west.
    after_show = datetime(2026, 7, 14, 23, 0, tzinfo=pacific)
    assert watch_window_open(after_show, show_date="2026-07-14", tz=pacific) is True


def test_watch_window_defaults_to_eastern():
    """Venue tz is unknown for some shows; ET is the documented fallback."""
    assert watch_window_open(
        datetime(2026, 7, 14, 23, 0, tzinfo=TZ), show_date="2026-07-14"
    )


def test_watch_from_hour_is_after_the_last_song():
    """Sanity-guard the constant: a show ending ~23:00 local must not be polled
    before it can plausibly be over."""
    assert WATCH_FROM_HOUR >= 22


# --- the summary push (one per show, not one per song) ---


def _card(combined=85, ppps=4.7):
    return {"combined": combined, "ppps": ppps, "show_date": "2026-07-14"}


def test_summary_push_leads_with_the_score():
    p = summary_push_payload(
        _card(), {"rank_by_total": 2, "shows_scored": 9, "is_best": False}, venue="MSG"
    )
    assert "85" in p["title"]


def test_summary_push_calls_out_a_personal_best():
    p = summary_push_payload(
        _card(120), {"rank_by_total": 1, "shows_scored": 9, "is_best": True}, venue="MSG"
    )
    blob = f"{p['title']} {p['body']}".lower()
    assert "best" in blob


def test_summary_push_ranks_a_non_best_night():
    p = summary_push_payload(
        _card(), {"rank_by_total": 2, "shows_scored": 9, "is_best": False}, venue="MSG"
    )
    assert "2" in p["body"]


def test_summary_push_does_not_claim_best_on_the_very_first_show():
    """is_best is trivially true with one scorecard; 'your best yet' out of a
    sample of one is a lie the user will notice immediately."""
    p = summary_push_payload(
        _card(), {"rank_by_total": 1, "shows_scored": 1, "is_best": True}, venue="MSG"
    )
    assert "best" not in f"{p['title']} {p['body']}".lower()


def test_summary_push_is_deduped_per_show():
    """A re-score (late phish.net correction on the next daily pass) must reuse
    the same tag so it replaces the old notification instead of stacking."""
    a = summary_push_payload(_card(), {"rank_by_total": 2, "shows_scored": 9}, venue="M")
    b = summary_push_payload(_card(99), {"rank_by_total": 1, "shows_scored": 9}, venue="M")
    assert a["tag"] == b["tag"]
    assert "2026-07-14" in a["tag"]


# --- the backstop must stay bounded ---


def test_backstop_window_is_bounded():
    """The canonical DB holds ~2,250 shows back to 1983. An unbounded 'close out
    every show with no scorecard' would reconcile the entire history of the band
    on first run — thousands of phish.net calls and thousands of bogus scorecards
    for shows that predate the app."""
    from phishpicker.close_out import BACKSTOP_DAYS

    assert 1 <= BACKSTOP_DAYS <= 7


def test_pending_close_outs_ignores_shows_outside_the_backstop_window(tmp_path):
    """Only shows within BACKSTOP_DAYS of now are candidates — a 1997 show must
    never come back as pending."""
    from types import SimpleNamespace

    from phishpicker.close_out import BACKSTOP_DAYS, pending_close_outs
    from phishpicker.db.connection import apply_live_schema, apply_schema, open_db

    read = open_db(tmp_path / "phishpicker.db")
    apply_schema(read)
    read.execute("INSERT INTO venues (venue_id, name, state) VALUES (1, 'MSG', 'NY')")
    read.executemany(
        "INSERT INTO shows (show_id, show_date, venue_id, fetched_at) "
        "VALUES (?, ?, 1, '2026-07-13T00:00:00Z')",
        [(1, "1997-12-31"), (2, "2026-07-12"), (3, "2026-07-14")],
    )
    read.commit()
    read.close()

    live = open_db(tmp_path / "live.db")
    apply_live_schema(live)
    live.close()

    settings = SimpleNamespace(
        db_path=tmp_path / "phishpicker.db",
        live_db_path=tmp_path / "live.db",
    )
    now = datetime(2026, 7, 14, 23, 0, tzinfo=TZ)
    dates = [s["show_date"] for s in pending_close_outs(settings, now)]

    assert "1997-12-31" not in dates
    assert "2026-07-14" in dates  # tonight's show, within the window
    assert all(
        d >= (now.date() - timedelta(days=BACKSTOP_DAYS)).isoformat() for d in dates
    )
