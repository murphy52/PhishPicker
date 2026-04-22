"""Map US state codes to IANA timezones for Phish venues we care about.

Phish plays a bounded set of venues; fallback to America/New_York is fine
because (a) it's the dominant region and (b) any mis-mapping is a cosmetic
countdown bug, not a correctness issue.
"""

_STATE_TZ = {
    "NV": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    "OR": "America/Los_Angeles",
    "AZ": "America/Phoenix",
    "CO": "America/Denver",
    "UT": "America/Denver",
    "NM": "America/Denver",
    "MT": "America/Denver",
    "WY": "America/Denver",
    "ID": "America/Denver",
    "TX": "America/Chicago",
    "IL": "America/Chicago",
    "MN": "America/Chicago",
    "WI": "America/Chicago",
    "MO": "America/Chicago",
    "TN": "America/Chicago",
    "AL": "America/Chicago",
    "LA": "America/Chicago",
    "AR": "America/Chicago",
    "OK": "America/Chicago",
    "KS": "America/Chicago",
    "IA": "America/Chicago",
    "NE": "America/Chicago",
    "MS": "America/Chicago",
}


def tz_for_state(state: str) -> str:
    return _STATE_TZ.get((state or "").upper(), "America/New_York")
