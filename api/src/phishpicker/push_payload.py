"""Web Push payload composition for live song notifications.

Split out of live_sync so the wording is a pure function of the scoring
data: it can be unit-tested, and POST /push/test can fire any variant at a
real device without a show running.

Layout is built for a locked phone, where the first line is often all that
shows: song name in the title, then slot, points, accuracy, and the running
Phish-vs-Picker score on their own body lines.

ICON CAVEAT: both stored subscriptions are Apple endpoints, and iOS Safari
is known to ignore the per-notification `icon` and render the installed web
app's icon instead. The outcome is therefore ALSO encoded in the title emoji,
which iOS does render — so the notification still reads correctly if the icon
is dropped. Probe a device with the `icon` override before investing in
artwork.
"""

ICON_SCORED = "/icon-scored-192.png"
ICON_MISS = "/icon-192.png"
ICON_BUSTOUT = "/icon-bustout-192.png"

# Human labels for the frozen-bracket outcome. Keys match scoring.py reasons.
_REASON_LABEL = {
    "opener": "nailed the opener",
    "exact": "exact slot",
    "right_set": "right set, wrong slot",
    "somewhere": "right show, wrong set",
    "next_song": "called it next",
}


def set_label(set_number: str) -> str:
    return "Encore" if set_number == "E" else f"Set {set_number}"


def rank_emoji(rank: int | None) -> str:
    if rank is None:
        return "🚨"
    if rank <= 3:
        return "🎯"
    if rank <= 10:
        return "🎵"
    if rank <= 20:
        return "🔍"
    return "🚨"


def points_suffix(att: dict) -> str:
    """A short 'points scored' tag for a push body, from a scoring
    attribution — or '' when the song banked nothing (issue #22).

    A bustout is celebrated (0 pts, but a fun rare song); a plain miss is
    silent so the notification isn't cluttered with '+0'.
    """
    if att.get("bustout"):
        return "🎸 Bustout!"
    final = att.get("final") or 0
    if final <= 0:
        return ""
    pts = int(final)
    if att.get("ledger") == "live":
        mult = att.get("mult")
        combo = f" ×{mult:g}" if mult and mult > 1 else ""
        return f"⚡ +{pts}{combo}"
    return f"🔮 +{pts}"


def _call_text(rank: int | None, probability: float | None) -> str:
    """The model's next-song call for this slot. Always says something —
    a blank line reads as a bug rather than as 'we didn't see it coming'."""
    if rank is None:
        return "unranked"
    pct = f" ({probability * 100:.0f}%)" if probability else ""
    return f"called #{rank}{pct}"


def _accuracy_text(att: dict | None, rank: int | None, probability: float | None) -> str:
    """How close we were, from both lenses: the frozen pre-show bracket and
    the live next-song call. They answer different questions and a song can
    hit on one while missing the other."""
    call = _call_text(rank, probability)
    reason = (att or {}).get("reason")
    label = _REASON_LABEL.get(reason) if reason else None
    if label:
        return f"{label} · {call}"
    return f"not in bracket · {call}"


def _icon_for(att: dict | None) -> str:
    if att and att.get("bustout"):
        return ICON_BUSTOUT
    if att and (att.get("final") or 0) > 0:
        return ICON_SCORED
    return ICON_MISS


def build_song_push(
    *,
    song_name: str,
    set_number: str,
    position_in_set: int,
    show_date: str,
    song_id: int,
    rank: int | None = None,
    probability: float | None = None,
    attribution: dict | None = None,
    versus: dict | None = None,
    icon: str | None = None,
) -> dict:
    """Compose the Web Push payload for one song landing in the setlist.

    `attribution` is the scoring row for this slot (None before scoring has
    run); `versus` is the running Phish-vs-Picker total (None if scoring
    failed — the notification degrades rather than being lost). `icon`
    overrides the outcome-derived icon, for probing what a device honours.
    """
    att = attribution or {}
    lines = []

    slot = f"{set_label(set_number)} · Slot {position_in_set}"
    suffix = points_suffix(att) if att else ""
    lines.append(f"{slot} · {suffix}" if suffix else slot)

    lines.append(_accuracy_text(attribution, rank, probability))

    if versus:
        picker = versus.get("picker_total", 0)
        phish = versus.get("phish_total", 0)
        lines.append(f"Phish {phish} — Picker {picker}")

    return {
        "title": f"{rank_emoji(rank)} {song_name}",
        "body": "\n".join(lines),
        "icon": icon or _icon_for(attribution),
        "badge": "/icon-192.png",
        "tag": f"phishpicker-{show_date}-{song_id}-{set_number}-{position_in_set}",
        "data": {"url": "/"},
    }
