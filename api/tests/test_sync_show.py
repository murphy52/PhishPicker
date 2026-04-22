from unittest.mock import MagicMock, patch

from pytest_httpx import HTTPXMock

from phishpicker.db.connection import open_db
from phishpicker.live_sync import sync_show_with_phishnet
from phishpicker.push import save_subscription


def test_sync_appends_net_rows_when_user_empty(
    httpx_mock: HTTPXMock, live_setup
):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {
                    "songid": 100,
                    "song": "Chalk Dust Torture",
                    "set": "1",
                    "position": 1,
                    "artist_name": "Phish",
                },
                {
                    "songid": 101,
                    "song": "Tweezer",
                    "set": "1",
                    "position": 2,
                    "artist_name": "Phish",
                },
            ]
        },
    )
    result = sync_show_with_phishnet(
        db_path=live_setup.db_path,
        live_db_path=live_setup.live_db_path,
        api_key="k",
        show_id=live_setup.show_id,
        show_date="2026-04-23",
    )
    assert result["status"] == "ok"
    assert result["appended"] == 2
    assert result["overrides"] == 0
    assert result["bustouts"] == 0
    assert result["last_updated"]

    # live_songs now holds both rows.
    with open_db(live_setup.live_db_path) as live:
        rows = live.execute(
            "SELECT song_id, set_number, entered_order FROM live_songs "
            "WHERE show_id = ? ORDER BY entered_order",
            (live_setup.show_id,),
        ).fetchall()
    assert [r["song_id"] for r in rows] == [100, 101]
    assert [r["set_number"] for r in rows] == ["1", "1"]


def test_sync_applies_override_when_user_disagrees(
    httpx_mock: HTTPXMock, live_setup
):
    # Pre-seed the live DB with 1 correct + 1 wrong song.
    from phishpicker.live import append_song

    with open_db(live_setup.live_db_path) as live:
        append_song(live, live_setup.show_id, song_id=100, set_number="1")
        append_song(live, live_setup.show_id, song_id=999, set_number="1")

    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {"songid": 100, "song": "Chalk Dust Torture", "set": "1",
                 "position": 1, "artist_name": "Phish"},
                {"songid": 101, "song": "Tweezer", "set": "1",
                 "position": 2, "artist_name": "Phish"},
            ]
        },
    )
    result = sync_show_with_phishnet(
        db_path=live_setup.db_path,
        live_db_path=live_setup.live_db_path,
        api_key="k",
        show_id=live_setup.show_id,
        show_date="2026-04-23",
    )
    assert result["appended"] == 0
    assert result["overrides"] == 1

    with open_db(live_setup.live_db_path) as live:
        rows = live.execute(
            "SELECT song_id, source, superseded_by FROM live_songs "
            "WHERE show_id = ? ORDER BY entered_order",
            (live_setup.show_id,),
        ).fetchall()
    assert rows[1]["song_id"] == 101
    assert rows[1]["source"] == "phishnet"
    assert rows[1]["superseded_by"] == 999


def test_sync_fires_push_with_rank_on_append(
    httpx_mock: HTTPXMock, live_setup
):
    """When scorer + vapid_private_key are supplied, an append should
    trigger a push whose body includes the model's rank for that slot."""
    # Pre-seed a push subscription so there's a target for send_push.
    with open_db(live_setup.live_db_path) as live:
        save_subscription(live, "https://push/x", "p", "a")

    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {"songid": 100, "song": "Chalk Dust Torture", "set": "1",
                 "position": 1, "artist_name": "Phish"},
            ]
        },
    )

    # Scorer stub that ranks song 100 as #1 with 25% probability.
    scorer = MagicMock()
    scorer.name = "stub"
    scorer.score_candidates.return_value = [(100, 10.0), (101, 5.0)]

    with patch("phishpicker.live_sync.predict_next_stateless") as pred, patch(
        "phishpicker.push.webpush"
    ) as wp:
        pred.return_value = [
            {"song_id": 100, "name": "Chalk Dust Torture", "score": 10.0,
             "probability": 0.25},
            {"song_id": 101, "name": "Tweezer", "score": 5.0,
             "probability": 0.12},
        ]
        sync_show_with_phishnet(
            db_path=live_setup.db_path,
            live_db_path=live_setup.live_db_path,
            api_key="k",
            show_id=live_setup.show_id,
            show_date="2026-04-23",
            scorer=scorer,
            vapid_private_key="fake-priv",
            vapid_subject="mailto:x@y.z",
        )

    # webpush should have been called at least once (push sent to the one sub).
    assert wp.called
    # And the payload should name the song + rank.
    call = wp.call_args
    body = call.kwargs["data"]
    assert "Chalk Dust Torture" in body
    assert "#1" in body
    assert "Slot 1" in body


def test_sync_skips_push_when_no_vapid_key(
    httpx_mock: HTTPXMock, live_setup
):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {"songid": 100, "song": "Chalk Dust Torture", "set": "1",
                 "position": 1, "artist_name": "Phish"},
            ]
        },
    )
    with patch("phishpicker.push.webpush") as wp:
        sync_show_with_phishnet(
            db_path=live_setup.db_path,
            live_db_path=live_setup.live_db_path,
            api_key="k",
            show_id=live_setup.show_id,
            show_date="2026-04-23",
            # no vapid key
        )
    wp.assert_not_called()


def test_sync_inserts_bustout_for_unknown_song(
    httpx_mock: HTTPXMock, live_setup
):
    httpx_mock.add_response(
        url="https://api.phish.net/v5/setlists/showdate/2026-04-23.json?apikey=k",
        json={
            "data": [
                {"songid": 99999, "song": "A Brand New Cover", "set": "1",
                 "position": 1, "artist_name": "Phish"},
            ]
        },
    )
    result = sync_show_with_phishnet(
        db_path=live_setup.db_path,
        live_db_path=live_setup.live_db_path,
        api_key="k",
        show_id=live_setup.show_id,
        show_date="2026-04-23",
    )
    assert result["appended"] == 1
    assert result["bustouts"] == 1

    # Song row should exist with is_bustout_placeholder=1.
    with open_db(live_setup.db_path, read_only=True) as db:
        row = db.execute(
            "SELECT song_id, is_bustout_placeholder FROM songs WHERE name = ?",
            ("A Brand New Cover",),
        ).fetchone()
    assert row is not None
    assert bool(row["is_bustout_placeholder"]) is True
