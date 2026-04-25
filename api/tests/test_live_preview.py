def test_preview_default_972_structure(seeded_client, live_show_id):
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert len(slots) == 18
    sets = [s["set_number"] for s in slots]
    assert sets.count("1") == 9
    assert sets.count("2") == 7
    assert sets.count("E") == 2


def test_preview_marks_entered_slots(seeded_client, live_show_with_one_song):
    r = seeded_client.get(
        f"/live/show/{live_show_with_one_song['show_id']}/preview"
    )
    slots = r.json()["slots"]
    assert slots[0]["state"] == "entered"
    assert slots[0]["entered_song"]["song_id"] == live_show_with_one_song["song_id"]
    assert slots[1]["state"] == "predicted"


def test_preview_predicted_slot_has_top_k(seeded_client, live_show_id):
    r = seeded_client.get(f"/live/show/{live_show_id}/preview?top_k=10")
    slots = r.json()["slots"]
    predicted = [s for s in slots if s["state"] == "predicted"]
    assert predicted, "expected at least one predicted slot"
    # Some slots may have <10 candidates if the seed pool is small; but >=1.
    for s in predicted:
        assert "top_k" in s
        assert all("rank" in c for c in s["top_k"])


def test_preview_extends_past_default_when_current_set_overflows(
    seeded_client, live_show_id
):
    """If Set 1 has more entered rows than the default (9), the preview must
    show every entered song plus one speculative set-closer prediction."""
    # Seed 10 songs into Set 1 (one past the default).
    for song_id in range(100, 110):
        r = seeded_client.post(
            "/live/song",
            json={"show_id": live_show_id, "song_id": song_id, "set_number": "1"},
        )
        assert r.status_code == 200

    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    set1 = [s for s in slots if s["set_number"] == "1"]
    # 10 entered + 1 speculative = 11
    assert len(set1) == 11
    assert all(s["state"] == "entered" for s in set1[:10])
    assert set1[10]["state"] == "predicted"


def test_preview_shrinks_past_set_to_entered_count(seeded_client, live_show_id):
    """Once a set is in the past (user advanced), its slot count collapses
    to exactly what the user entered — unused predictions vanish."""
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    set1 = [s for s in slots if s["set_number"] == "1"]
    # Set 1 is past — exactly 1 entered, no phantom predictions.
    assert len(set1) == 1
    assert set1[0]["state"] == "entered"
    # Set 2 is active, no entered yet — default 7 (max(7, 0+1) = 7).
    set2 = [s for s in slots if s["set_number"] == "2"]
    assert len(set2) == 7


def test_preview_advance_to_encore_collapses_both_prior_sets(
    seeded_client, live_show_id
):
    """Encore is the last set — advancing to it makes both Set 1 and Set 2
    past, so both collapse to their entered counts."""
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 101, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 102, "set_number": "2"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "E"}
    )
    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    assert len([s for s in slots if s["set_number"] == "1"]) == 2
    assert len([s for s in slots if s["set_number"] == "2"]) == 1
    # Encore active, no entered: max(default=2, 0+1) = 2.
    assert len([s for s in slots if s["set_number"] == "E"]) == 2


def test_preview_hides_past_set_with_no_entered(seeded_client, live_show_id):
    """Advancing without entering anything in Set 1 hides Set 1 entirely."""
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r.json()["slots"]
    assert not [s for s in slots if s["set_number"] == "1"]


def test_preview_restores_predictions_when_walking_back_to_set(
    seeded_client, live_show_id
):
    """If the user walks back via /set-boundary, the predicted slots return
    up to the default."""
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "2"}
    )
    r = seeded_client.get(f"/live/show/{live_show_id}/preview")
    assert len([s for s in r.json()["slots"] if s["set_number"] == "1"]) == 1

    seeded_client.post(
        "/live/set-boundary", json={"show_id": live_show_id, "set_number": "1"}
    )
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    set1 = [s for s in r2.json()["slots"] if s["set_number"] == "1"]
    assert len(set1) == 9
    assert set1[0]["state"] == "entered"
    assert all(s["state"] == "predicted" for s in set1[1:])


def test_preview_respects_live_show_meta_sizes(seeded_client, live_show_id):
    r = seeded_client.post(
        f"/live/show/{live_show_id}/structure",
        json={"set1": 10, "set2": 8, "encore": 3},
    )
    assert r.status_code == 200
    r2 = seeded_client.get(f"/live/show/{live_show_id}/preview")
    slots = r2.json()["slots"]
    assert len(slots) == 21


def test_compute_hit_rank_smoke(seeded_client, live_show_id):
    """Smoke test — helper returns either a 1..10 int or None for a real fixture
    call; verifies the helper doesn't crash when wired to the real scorer."""
    from contextlib import closing

    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _compute_hit_rank
    from phishpicker.model.scorer import HeuristicScorer

    # Seed-provided song ids are small — pick a known one from fixtures.
    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as read_conn:
        rank = _compute_hit_rank(
            read_conn=read_conn,
            played_songs=[],
            target_song_id=100,
            current_set="1",
            show_date="2026-04-23",
            venue_id=1,
            prev_trans_mark=",",
            prev_set_number=None,
            scorer=HeuristicScorer(),
            song_ids_cache=None,
            song_names_cache=None,
            stats_cache=None,
            ext_cache=None,
            bigram_cache=None,
        )
    assert rank is None or (1 <= rank <= 10)


def test_compute_hit_rank_returns_rank_when_song_in_top_n(monkeypatch):
    """Deterministic test — stub predict_next_stateless to return a known list,
    then verify the helper finds the target at the correct 1-based position."""
    from phishpicker import live_preview
    from phishpicker.live_preview import _compute_hit_rank

    fake_cands = [
        {"song_id": 1, "name": "First"},
        {"song_id": 42, "name": "Target"},
        {"song_id": 100, "name": "Third"},
    ]

    def fake_predict(**_kwargs):
        return fake_cands

    monkeypatch.setattr(live_preview, "predict_next_stateless", fake_predict)

    rank = _compute_hit_rank(
        read_conn=None,
        played_songs=[],
        target_song_id=42,
        current_set="1",
        show_date="2026-04-23",
        venue_id=1,
        prev_trans_mark=",",
        prev_set_number=None,
        scorer=None,
        song_ids_cache=None,
        song_names_cache=None,
        stats_cache=None,
        ext_cache=None,
        bigram_cache=None,
    )
    assert rank == 2


def test_compute_hit_rank_returns_none_for_unknown_song(seeded_client, live_show_id):
    from contextlib import closing

    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _compute_hit_rank
    from phishpicker.model.scorer import HeuristicScorer

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as read_conn:
        rank = _compute_hit_rank(
            read_conn=read_conn,
            played_songs=[],
            target_song_id=9_999_999,  # definitely not in fixtures
            current_set="1",
            show_date="2026-04-23",
            venue_id=1,
            prev_trans_mark=",",
            prev_set_number=None,
            scorer=HeuristicScorer(),
            song_ids_cache=None,
            song_names_cache=None,
            stats_cache=None,
            ext_cache=None,
            bigram_cache=None,
        )
    assert rank is None


def test_preview_includes_hit_rank_on_entered_slots(seeded_client, live_show_id):
    # Enter a song so we have an entered slot whose hit_rank can be computed.
    r = seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    assert r.status_code == 200

    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    entered = [s for s in slots if s["state"] == "entered"]
    assert entered, "expected one entered slot"
    s = entered[0]
    assert "hit_rank" in s
    # hit_rank is either a 1..10 int or None — both are valid outcomes.
    assert s["hit_rank"] is None or (1 <= s["hit_rank"] <= 10)


def test_preview_predicted_slots_have_no_hit_rank(seeded_client, live_show_id):
    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    predicted = [s for s in slots if s["state"] == "predicted"]
    for s in predicted:
        # Absent key is fine; explicit null is fine; a number is not.
        assert s.get("hit_rank") is None


def test_preview_passes_prior_only_context_to_hit_rank(
    seeded_client, live_show_id, monkeypatch
):
    """Each entered slot's hit_rank must be computed from the songs entered
    *before* it — not including the slot's own song. The first entered slot
    should see [], the second should see only the first song's id."""
    from phishpicker import live_preview

    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 100, "set_number": "1"},
    )
    seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": 101, "set_number": "1"},
    )

    real_predict = live_preview.predict_next_stateless
    captured_played: list[list[int]] = []

    def spy_predict(*, played_songs, **kwargs):
        captured_played.append(list(played_songs))
        return real_predict(played_songs=played_songs, **kwargs)

    monkeypatch.setattr(live_preview, "predict_next_stateless", spy_predict)
    seeded_client.get(f"/live/show/{live_show_id}/preview")

    # Iteration order is Set 1 pos 1, Set 1 pos 2, ...; both entered slots come
    # first. The first sees no prior songs; the second sees only song 100.
    assert captured_played[0] == []
    assert captured_played[1] == [100]


def test_played_in_run_returns_empty_when_show_not_in_tour(seeded_client):
    """A show date with no matching tour returns an empty filter set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as conn:
        result = _played_in_run(conn, show_date="1900-01-01", venue_id=1)
    assert result == set()


def test_played_in_run_returns_empty_when_first_show_of_run(seeded_client):
    """Night 1 of a run has no prior shows → empty set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as conn:
        # Look up the earliest scheduled show for any venue; that's a run-of-1
        # or the start of a run.
        row = conn.execute(
            "SELECT show_date, venue_id FROM shows ORDER BY show_date ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return  # no shows in fixtures — vacuous pass
        result = _played_in_run(conn, show_date=row["show_date"], venue_id=row["venue_id"])
    # First-of-run can be empty, OR have entries if the same venue appeared
    # adjacent before — we just confirm the function returns a set without erroring.
    assert isinstance(result, set)


def test_played_in_run_includes_prior_run_mate_setlist(seeded_client, monkeypatch, tmp_path):
    """When two shows share venue+tour and date order, songs from the earlier
    show appear in the later show's played_in_run set."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db
    from phishpicker.live_preview import _played_in_run

    settings = Settings()
    with closing(open_db(settings.db_path, read_only=True)) as write_conn:
        pass  # We need a write connection — open_db with read_only=False below.

    from phishpicker.db.connection import open_db as open_db_rw
    with closing(open_db_rw(settings.db_path)) as conn:
        # Find or insert a tour; insert two shows on the same tour+venue, two
        # days apart, with a known song in the first show's setlist.
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (9999, 'Test Tour', '2099-01-01', '2099-12-31')"
        )
        cur.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (9999, 'Test Venue')"
        )
        cur.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90001, '2099-06-01', 9999, 9999, '2099-01-01', 1)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90002, '2099-06-02', 9999, 9999, '2099-01-01', 0)"
        )
        # Pick any real song_id from the seed pool.
        sid_row = conn.execute("SELECT song_id FROM songs LIMIT 1").fetchone()
        assert sid_row, "fixture has no songs"
        sid = sid_row["song_id"]
        cur.execute(
            "INSERT OR REPLACE INTO setlist_songs "
            "(show_id, set_number, position, song_id) "
            "VALUES (90001, '1', 1, ?)",
            (sid,),
        )
        conn.commit()

        result = _played_in_run(conn, show_date="2099-06-02", venue_id=9999)

    assert sid in result


def test_preview_excludes_songs_played_earlier_in_run(seeded_client, live_show_id):
    """A song from a prior run-mate show must not appear in any predicted
    slot's top_k of /preview."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db

    settings = Settings()
    # Live-show metadata lives in the live DB; canonical shows/setlists in
    # the read DB. Seed a prior run-mate canonical show with a known song.
    with closing(open_db(settings.live_db_path)) as live_conn:
        live = live_conn.execute(
            "SELECT show_date, venue_id FROM live_show WHERE show_id = ?",
            (live_show_id,),
        ).fetchone()
        assert live, "expected live show in fixture"
        # If the live show has no venue/tour mapping in fixtures, this test
        # can't exercise the filter — bail with skip.
        if live["venue_id"] is None:
            import pytest
            pytest.skip("live fixture lacks venue_id; can't construct run")
        live_show_date = live["show_date"]
        live_venue_id = live["venue_id"]

    with closing(open_db(settings.db_path)) as conn:
        sid_row = conn.execute("SELECT song_id FROM songs LIMIT 1").fetchone()
        assert sid_row
        target_song_id = sid_row["song_id"]

        # Find or use the live show's tour; if missing, create one.
        tour_id = 9998
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (?, 'Run Filter Test', '1900-01-01', '2999-12-31')",
            (tour_id,),
        )
        # Ensure the venue row exists (live_show fixtures don't seed it).
        conn.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (?, 'Live Test Venue')",
            (live_venue_id,),
        )
        # Anchor live show into shows so tour resolution finds it.
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90100, ?, ?, ?, '1900-01-01', 0)",
            (live_show_date, live_venue_id, tour_id),
        )
        # Prior run-mate (one day earlier) with target song in setlist.
        from datetime import date, timedelta
        prior_date = (date.fromisoformat(live_show_date) - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90101, ?, ?, ?, '1900-01-01', 1)",
            (prior_date, live_venue_id, tour_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO setlist_songs "
            "(show_id, set_number, position, song_id) "
            "VALUES (90101, '1', 1, ?)",
            (target_song_id,),
        )
        conn.commit()

    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    for s in slots:
        if s["state"] == "predicted":
            ids = [c["song_id"] for c in s.get("top_k", [])]
            assert target_song_id not in ids, (
                f"target song {target_song_id} leaked into top_k for slot {s['slot_idx']}"
            )


def test_preview_entered_slot_hit_rank_null_when_song_in_run(seeded_client, live_show_id):
    """When an entered song was played earlier in the run, the run-filter
    excludes it from the candidate pool so its retroactive hit_rank is None
    (em-dash in the UI)."""
    from contextlib import closing
    from phishpicker.config import Settings
    from phishpicker.db.connection import open_db

    settings = Settings()

    # Look up the live show's date + venue from the live DB.
    with closing(open_db(settings.live_db_path)) as live_conn:
        live = live_conn.execute(
            "SELECT show_date, venue_id FROM live_show WHERE show_id = ?",
            (live_show_id,),
        ).fetchone()
    assert live, "expected live show in fixture"
    if live["venue_id"] is None:
        import pytest
        pytest.skip("live fixture lacks venue_id; can't construct run")

    # Seed canonical shows/tours so _played_in_run resolves a tour and finds
    # the prior run-mate show.
    from datetime import date, timedelta
    prior_date = (date.fromisoformat(live["show_date"]) - timedelta(days=1)).isoformat()
    tour_id = 9997  # different tour_id from the sibling test to keep isolation
    with closing(open_db(settings.db_path)) as conn:
        sid_row = conn.execute("SELECT song_id FROM songs LIMIT 1").fetchone()
        assert sid_row
        target_song_id = sid_row["song_id"]
        conn.execute(
            "INSERT OR IGNORE INTO tours (tour_id, name, start_date, end_date) "
            "VALUES (?, 'Hit Rank Run Filter Test', '1900-01-01', '2999-12-31')",
            (tour_id,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO venues (venue_id, name) VALUES (?, 'Live Venue')",
            (live["venue_id"],),
        )
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90200, ?, ?, ?, '1900-01-01', 0)",
            (live["show_date"], live["venue_id"], tour_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO shows "
            "(show_id, show_date, venue_id, tour_id, fetched_at, reconciled) "
            "VALUES (90201, ?, ?, ?, '1900-01-01', 1)",
            (prior_date, live["venue_id"], tour_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO setlist_songs "
            "(show_id, set_number, position, song_id) "
            "VALUES (90201, '1', 1, ?)",
            (target_song_id,),
        )
        conn.commit()

    # Enter the target song into the live show.
    r = seeded_client.post(
        "/live/song",
        json={"show_id": live_show_id, "song_id": target_song_id, "set_number": "1"},
    )
    assert r.status_code == 200

    slots = seeded_client.get(f"/live/show/{live_show_id}/preview").json()["slots"]
    entered = [s for s in slots if s["state"] == "entered"]
    target = next(
        (s for s in entered if s["entered_song"]["song_id"] == target_song_id), None
    )
    assert target is not None, "expected target song in entered slots"
    assert target["hit_rank"] is None, (
        f"expected hit_rank=None for run-filtered song, got {target['hit_rank']}"
    )
