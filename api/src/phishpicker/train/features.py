"""Feature schema for the LightGBM ranker.

FEATURE_COLUMNS is the authoritative column list (names + order).
Runtime and training both go through FeatureRow → to_vector() → numpy;
that guarantees training-serving parity by construction.

Missing numeric values (never-played recency, absent tour, etc.) are encoded as
sentinels (MISSING_INT = -1, MISSING_FLOAT = -1.0). LightGBM handles sentinels
natively — we do NOT substitute column means.
"""

from dataclasses import asdict, dataclass, fields

MISSING_INT: int = -1
MISSING_FLOAT: float = -1.0


@dataclass
class FeatureRow:
    # Identity (not features, excluded from to_vector).
    song_id: int
    show_id: int
    slot_number: int

    # 1. Song base rates
    total_plays_ever: int = 0
    plays_last_12mo: int = 0
    debut_year: int = MISSING_INT
    is_cover: int = 0

    # 2. Recency
    shows_since_last_played_anywhere: int = MISSING_INT
    days_since_last_played_anywhere: int = MISSING_INT
    shows_since_last_played_this_tour: int = MISSING_INT

    # 3. Venue & run
    times_at_venue: int = 0
    shows_since_last_at_venue: int = MISSING_INT
    played_already_this_run: int = 0
    run_position: int = 1
    run_length_total: int = 1
    frac_run_remaining: float = 0.0
    venue_debut_affinity: float = 0.0

    # 4. Tour
    tour_position: int = 1
    times_this_tour: int = 0
    tour_opener_rate: float = 0.0
    tour_closer_rate: float = 0.0

    # 5. In-show context
    current_set: int = 1
    set_position: int = 1
    # Explicit slot-type flags. Trees can learn set-2 and opener behavior via
    # (current_set, set_position) splits but our slot-conditional SHAP analysis
    # showed the model wasn't finding those interactions — set-2-mid/closer
    # slots had no slot-specific features firing. These flags give trees a
    # single-split path to slot type so slot-specific rates can engage.
    is_set2: int = 0
    is_first_in_set: int = 0
    set1_opener_rate: float = 0.0
    set2_opener_rate: float = 0.0
    encore_rate: float = 0.0
    middle_rate: float = 0.0
    prev_song_id: int = MISSING_INT
    bigram_prev_to_this: float = 0.0
    segue_mark_in: int = 0
    # Opener-rotation signals — "haven't opened with it since Charleston" heuristic.
    shows_since_last_set1_opener: int = MISSING_INT
    shows_since_last_any_opener_role: int = MISSING_INT
    # Warm-up / jam-vehicle proxy — low value = early-slot song, high = late-show jam.
    avg_set_position_when_played: float = MISSING_FLOAT

    # 6. Temporal / era
    day_of_week: int = 0
    month: int = 1
    days_since_last_new_album: int = MISSING_INT
    is_from_latest_album: int = 0
    era: int = 3
    # Album-recency substitutes (no /albums endpoint on phish.net).
    days_since_debut: int = MISSING_INT
    plays_last_6mo: int = 0
    # Ratio of recent 6mo plays to preceding 6mo plays. >1 = heating up.
    recent_play_acceleration: float = 0.0

    # 7. Derived role scores
    closer_score: float = 0.0
    bustout_score: float = 0.0

    @classmethod
    def empty(cls, song_id: int, show_id: int, slot_number: int) -> "FeatureRow":
        return cls(song_id=song_id, show_id=show_id, slot_number=slot_number)

    def to_vector(self) -> list[float]:
        d = asdict(self)
        return [float(d[col]) for col in FEATURE_COLUMNS]


_IDENTITY = {"song_id", "show_id", "slot_number"}
FEATURE_COLUMNS: tuple[str, ...] = tuple(
    f.name for f in fields(FeatureRow) if f.name not in _IDENTITY
)
