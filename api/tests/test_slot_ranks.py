"""Slot-walk + per-slot rank computation, shared between nightly-smoke
and the post-show review endpoint."""

from dataclasses import dataclass

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.slot_ranks import SlotRank, compute_slot_ranks


@dataclass
class FakeScorer:
    """Returns scores that put a fixed list of songs at the top in order.
    Anything not in the list scores 0. Used to assert rank computation."""
    name: str
    top_order: list[int]

    def score_candidates(self, **kwargs):
        candidate_song_ids = kwargs["candidate_song_ids"]
        scores = []
        for sid in candidate_song_ids:
            if sid in self.top_order:
                scores.append((sid, 100.0 - self.top_order.index(sid)))
            else:
                scores.append((sid, 0.0))
        return scores


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ranks.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'Sphere');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at)
        VALUES (100, '2026-04-25', 10, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (100, '1', 1, 2), (100, '1', 2, 1),
            (100, '2', 1, 3), (100, 'E', 1, 4);
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_compute_slot_ranks_returns_one_row_per_slot(conn):
    scorer = FakeScorer(name="t", top_order=[1, 2, 3, 4])
    rows = compute_slot_ranks(conn, show_id=100, scorer=scorer)
    assert [r.slot_idx for r in rows] == [1, 2, 3, 4]
    assert [r.set_number for r in rows] == ["1", "1", "2", "E"]
    assert [r.actual_song_id for r in rows] == [2, 1, 3, 4]
    assert all(isinstance(r, SlotRank) for r in rows)


def test_compute_slot_ranks_orders_encore_after_numbered_sets(tmp_path):
    """Encores ('E', 'E2') must sort after numbered sets ('1', '2', '3'),
    matching nightly_smoke._slot_sort_key. Lex order would mostly work
    ('1' < 'E') but 'E2' would lex-sort before any numbered set.
    """
    c = open_db(tmp_path / "ord.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO songs (song_id, name, first_seen_at) VALUES
            (1, 'A', '2020-01-01'), (2, 'B', '2020-01-01'),
            (3, 'C', '2020-01-01'), (4, 'D', '2020-01-01'),
            (5, 'E', '2020-01-01');
        INSERT INTO venues (venue_id, name) VALUES (10, 'V');
        INSERT INTO shows (show_id, show_date, venue_id, fetched_at)
        VALUES (200, '2026-04-25', 10, '2026-04-26');
        INSERT INTO setlist_songs (show_id, set_number, position, song_id) VALUES
            (200, '1', 1, 1),
            (200, '3', 1, 3),
            (200, 'E', 1, 4),
            (200, 'E2', 1, 5);
        """
    )
    c.commit()
    scorer = FakeScorer(name="t", top_order=[1, 3, 4, 5])
    rows = compute_slot_ranks(c, show_id=200, scorer=scorer)
    c.close()
    assert [r.set_number for r in rows] == ["1", "3", "E", "E2"]


def test_compute_slot_ranks_finds_actual_rank_in_scored_order(conn):
    # Scorer puts B (id=2) at top, then A (1), then C (3), then D (4).
    # Slot 1 actual = B → rank 1. Slot 2 actual = A → rank 2.
    # Slot 3 actual = C → rank 3. Slot 4 actual = D → rank 4.
    scorer = FakeScorer(name="t", top_order=[2, 1, 3, 4])
    rows = compute_slot_ranks(conn, show_id=100, scorer=scorer)
    assert rows[0].actual_rank == 1
    assert rows[1].actual_rank == 2
    assert rows[2].actual_rank == 3
    assert rows[3].actual_rank == 4


def test_compute_slot_ranks_returns_none_when_song_not_in_pool(conn):
    # Scorer pool excludes song id=4 → its rank is None.
    class PoolScorer:
        name = "t"
        def score_candidates(self, **kwargs):
            return [
                (sid, 100.0)
                for sid in kwargs["candidate_song_ids"]
                if sid != 4
            ]
    rows = compute_slot_ranks(conn, show_id=100, scorer=PoolScorer())
    assert rows[3].actual_rank is None


def test_compute_slot_ranks_resets_slots_into_current_set_at_set_change(conn):
    # The encore slot must have slots_into_current_set=1, not 4.
    captured: list[dict] = []

    class Capture:
        name = "t"

        def score_candidates(self, **kwargs):
            captured.append(dict(kwargs))
            return [(sid, 1.0) for sid in kwargs["candidate_song_ids"]]

    compute_slot_ranks(conn, show_id=100, scorer=Capture())
    assert captured[0]["slots_into_current_set"] == 1  # set 1, pos 1
    assert captured[1]["slots_into_current_set"] == 2  # set 1, pos 2
    assert captured[2]["slots_into_current_set"] == 1  # set 2 starts
    assert captured[3]["slots_into_current_set"] == 1  # encore starts
