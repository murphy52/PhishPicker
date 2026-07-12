"""Tests for the show-level 'Likely Tonight' inclusion model."""

from pathlib import Path

import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.inclusion import likely_tonight, load_inclusion_scorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    InclusionHistory,
)
from phishpicker.train.inclusion_runner import train_inclusion


def _build_db(path: Path):
    c = open_db(path)
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO tours (tour_id, name) VALUES (1, 'Test Tour');
        INSERT INTO songs (song_id, name, first_seen_at, debut_date, original_artist) VALUES
            (1, 'Staple',   '2019-01-01', '2019-01-01', 'Phish'),
            (2, 'Frequent', '2019-01-01', '2019-01-01', 'Phish'),
            (3, 'Rare',     '2019-01-01', '2019-01-01', 'Phish'),
            (4, 'NeverPlayed','2019-01-01','2019-01-01', 'Phish');
        """
    )
    # 40 shows, monotonically increasing dates. Song 1 every show, song 2 most
    # shows, song 3 rarely, song 4 never.
    for i in range(40):
        show_id = 1000 + i
        show_date = f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        c.execute(
            "INSERT INTO shows (show_id, show_date, fetched_at, tour_id, tour_position) "
            "VALUES (?, ?, ?, 1, ?)",
            (show_id, show_date, show_date, i + 1),
        )
        rows = [(show_id, "1", 1, 1)]
        if i % 2 == 0:
            rows.append((show_id, "1", 2, 2))
        if i % 13 == 0:
            rows.append((show_id, "1", 3, 3))
        c.executemany(
            "INSERT INTO setlist_songs (show_id, set_number, position, song_id) "
            "VALUES (?,?,?,?)",
            rows,
        )
    c.commit()
    return c


def test_features_are_leak_free(tmp_path):
    """total_plays_ever for a show must count only plays STRICTLY before it."""
    conn = _build_db(tmp_path / "incl.db")
    hist = InclusionHistory(conn)
    idx = INCLUSION_FEATURE_COLUMNS.index("total_plays_ever")

    # Song 1 plays in every show; at the k-th show it should have k prior plays.
    shows = sorted(hist.shows, key=lambda s: s["show_date"])
    for k in (5, 10, 20):
        ctx = hist.context_for(shows[k]["show_id"])
        row = hist.feature_row(1, ctx)
        assert row is not None
        assert row[idx] == k, f"expected {k} prior plays, got {row[idx]}"
    conn.close()


def test_candidate_excludes_never_played(tmp_path):
    conn = _build_db(tmp_path / "incl.db")
    hist = InclusionHistory(conn)
    last = sorted(hist.shows, key=lambda s: s["show_date"])[-1]
    ctx = hist.context_for(last["show_id"])
    cands = hist.candidate_ids(ctx.show_date)
    assert 1 in cands and 2 in cands
    assert 4 not in cands  # never played -> not a candidate


def test_train_and_serve_ranks_staple_over_rare(tmp_path):
    conn = _build_db(tmp_path / "incl.db")
    out = tmp_path / "inclusion_model.lgb"
    res = train_inclusion(tmp_path / "incl.db", out, holdout_days=30, num_boost_round=60, warmup_shows=5)
    assert res["recall_at_25"] >= 0.0
    assert Path(out).exists()

    scorer = load_inclusion_scorer(out)
    ranked = likely_tonight(conn, sorted(hist_ids(conn))[-1], scorer, top_n=10)
    names = [r["name"] for r in ranked]
    assert names, "expected non-empty Likely Tonight list"
    assert "NeverPlayed" not in names
    # The every-show staple should outrank the rarely-played song.
    assert names.index("Staple") < names.index("Rare")
    conn.close()


def hist_ids(conn):
    return [r[0] for r in conn.execute("SELECT show_id FROM shows").fetchall()]


def test_scorer_schema_guard(tmp_path):
    """A model trained on a different column set must be rejected at load."""
    conn = _build_db(tmp_path / "incl.db")
    out = tmp_path / "inclusion_model.lgb"
    train_inclusion(tmp_path / "incl.db", out, holdout_days=30, num_boost_round=30, warmup_shows=5)
    # Sanity: the shipped meta matches the serving contract.
    scorer = load_inclusion_scorer(out)
    assert list(scorer.feature_columns) == INCLUSION_FEATURE_COLUMNS
    with pytest.raises(ValueError):
        scorer.assert_compatible_with(["only", "two"])
    conn.close()
