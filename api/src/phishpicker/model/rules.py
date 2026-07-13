_REPRISE_SUFFIX = " reprise"

# How hard to demote a reprise whose base song hasn't been played tonight.
# Empirically 91% of encore Tweezer Reprises (193/213) follow a Tweezer earlier
# in the same show; the remaining ~9% are genuine standalone gags (NYE,
# cross-night callbacks). A soft demote — not a hard exclude — is what keeps
# that tail reachable.
REPRISE_PENALTY = 0.1


def build_reprise_deps(song_names: dict[int, str]) -> dict[int, int]:
    """Map each reprise song to the base song it depends on.

    Derived from names ("Tweezer Reprise" -> "Tweezer") rather than a hardcoded
    id list, so it survives a DB rebuild and picks up any future reprise. A
    reprise whose base song isn't in the catalog is skipped — it has no
    dependency to enforce.
    """
    by_name = {name.strip().lower(): sid for sid, name in song_names.items()}
    deps: dict[int, int] = {}
    for sid, name in song_names.items():
        lowered = name.strip().lower()
        if not lowered.endswith(_REPRISE_SUFFIX):
            continue
        base = by_name.get(lowered[: -len(_REPRISE_SUFFIX)].strip())
        if base is not None:
            deps[sid] = base
    return deps


def apply_post_rules(
    scored: list[tuple[int, float]],
    played_tonight: set[int],
    played_in_run: set[int] | None = None,
    reprise_deps: dict[int, int] | None = None,
) -> list[tuple[int, float]]:
    excluded = played_tonight if played_in_run is None else played_tonight | played_in_run
    out: list[tuple[int, float]] = []
    for sid, score in scored:
        if sid in excluded:
            out.append((sid, 0.0))
            continue
        # The dependency is same-show, not same-run: a Tweezer two nights ago
        # doesn't license a Tweezer Reprise tonight, so this checks
        # played_tonight rather than `excluded`.
        base = reprise_deps.get(sid) if reprise_deps else None
        if base is not None and base not in played_tonight:
            score *= REPRISE_PENALTY
        out.append((sid, score))
    return out
