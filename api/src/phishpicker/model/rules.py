def apply_post_rules(
    scored: list[tuple[int, float]],
    played_tonight: set[int],
    played_in_run: set[int] | None = None,
) -> list[tuple[int, float]]:
    excluded = played_tonight if played_in_run is None else played_tonight | played_in_run
    return [(sid, 0.0 if sid in excluded else s) for sid, s in scored]
