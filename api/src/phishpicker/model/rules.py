def apply_post_rules(
    scored: list[tuple[int, float]], played_tonight: set[int]
) -> list[tuple[int, float]]:
    return [(sid, 0.0 if sid in played_tonight else s) for sid, s in scored]
