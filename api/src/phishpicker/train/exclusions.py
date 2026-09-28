"""Shows kept out of training labels and holdout evaluation.

A show belongs here when its setlist was a one-off themed event that says
nothing about how Phish builds a normal show, so learning from it (or grading
the model on it) would skew both.

Excluded shows still count as history: their songs feed plays, gaps and
bigrams like any other show. They happened, and the live app, the scoring game
and phish.net's gap counts all see them.
"""

EXCLUDED_SHOW_IDS: frozenset[int] = frozenset(
    {
        # Madison Square Garden, July 2026: five nights of 1992–96 retro sets.
        1771439218,  # 2026-07-22
        1771439237,  # 2026-07-24
        1771439266,  # 2026-07-25
        1771439284,  # 2026-07-27
        1771439309,  # 2026-07-29
    }
)
