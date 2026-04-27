import asyncio
import hmac
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

from phishpicker.config import Settings
from phishpicker.db.connection import open_db
from phishpicker.live import (
    advance_set,
    append_song,
    create_live_show,
    delete_last_song,
    get_live_show,
)
from phishpicker.live_sync import PollerRegistry
from phishpicker.model.scorer import load_runtime_scorer
from phishpicker.phishnet.client import PhishNetClient
from phishpicker.predict import predict_next, predict_next_stateless
from phishpicker.venue_tz import tz_for_state

log = logging.getLogger(__name__)


# Per-request connections (not shared on app.state). sqlite3.Connection is
# thread-affine; FastAPI runs sync routes in a threadpool, so a single shared
# connection raises ProgrammingError under concurrency. Per-request connections
# are cheap in WAL mode and sidestep this entirely. They also naturally pick
# up post-ship DB swaps on the NAS without a reload dance.
def _read_conn_dep(settings: Settings) -> Iterator[sqlite3.Connection]:
    def _dep() -> Iterator[sqlite3.Connection]:
        with closing(open_db(settings.db_path, read_only=True)) as c:
            yield c

    return _dep


def _live_conn_dep(settings: Settings) -> Iterator[sqlite3.Connection]:
    def _dep() -> Iterator[sqlite3.Connection]:
        with closing(open_db(settings.live_db_path)) as c:
            yield c

    return _dep


def _read_write_conn_dep(settings: Settings) -> Iterator[sqlite3.Connection]:
    def _dep() -> Iterator[sqlite3.Connection]:
        with closing(open_db(settings.db_path, read_only=False)) as c:
            yield c

    return _dep


def _residency_position(
    conn: sqlite3.Connection, show_id: int
) -> tuple[int | None, int | None]:
    """Return (position, length) for the given show within its residency,
    where "residency" = all shows with the same venue_id + tour_id.

    Returns (None, None) when the show isn't in the canonical DB, lacks a
    venue_id or tour_id, or is the only show in its residency (length=1).
    """
    canonical = conn.execute(
        "SELECT venue_id, tour_id, show_date FROM shows WHERE show_id = ?",
        (show_id,),
    ).fetchone()
    if not canonical or canonical["venue_id"] is None or canonical["tour_id"] is None:
        return None, None
    length = conn.execute(
        "SELECT COUNT(*) FROM shows WHERE venue_id = ? AND tour_id = ?",
        (canonical["venue_id"], canonical["tour_id"]),
    ).fetchone()[0]
    if length < 2:
        return None, None
    position = conn.execute(
        "SELECT COUNT(*) FROM shows "
        "WHERE venue_id = ? AND tour_id = ? AND show_date <= ?",
        (canonical["venue_id"], canonical["tour_id"], canonical["show_date"]),
    ).fetchone()[0]
    return position, length


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.model_path = settings.data_dir / "model.lgb"
        app.state.metrics_path = settings.data_dir / "metrics.json"
        app.state.scorer = load_runtime_scorer(app.state.model_path)
        log.info("loaded scorer: %s", app.state.scorer.name)
        app.state.phishnet_client = PhishNetClient(api_key=settings.phishnet_api_key)
        app.state.pollers = PollerRegistry()
        try:
            yield
        finally:
            await app.state.pollers.stop_all()
            app.state.phishnet_client.close()

    app = FastAPI(title="Phishpicker", lifespan=lifespan)
    get_read = _read_conn_dep(settings)
    get_live = _live_conn_dep(settings)
    get_rw = _read_write_conn_dep(settings)
    # Expose dependency factories on app.state so endpoints in other modules
    # can access them via request.app.state.
    app.state.get_read = get_read
    app.state.get_live = get_live
    app.state.get_rw = get_rw

    class LiveShowCreate(BaseModel):
        show_date: str
        venue_id: int | None = None

    class LiveSongAppend(BaseModel):
        show_id: str
        song_id: int
        set_number: str
        trans_mark: str = ","

    class SetBoundary(BaseModel):
        show_id: str
        set_number: str

    @app.get("/meta")
    def meta(request: Request, conn: sqlite3.Connection = Depends(get_read)):  # noqa: B008
        shows = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
        songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        latest = conn.execute("SELECT MAX(show_date) FROM shows").fetchone()[0]
        # MAX(show_date) only over shows that actually have setlist rows —
        # exposes ingest freshness so a stale-DB regression is visible from
        # one curl. Different from latest_show_date, which can be far in the
        # future via placeholder rows for upcoming shows.
        last_setlist = conn.execute(
            "SELECT MAX(s.show_date) FROM shows s "
            "WHERE EXISTS (SELECT 1 FROM setlist_songs ss WHERE ss.show_id = s.show_id)"
        ).fetchone()[0]
        return {
            "shows_count": shows,
            "songs_count": songs,
            "latest_show_date": latest,
            "last_setlist_date": last_setlist,
            "data_snapshot_at": datetime.now(UTC).isoformat(),
            "version": "0.1.0-skeleton",
            "scorer": request.app.state.scorer.name,
            "model_sha": request.app.state.scorer.sha,
        }

    @app.get("/about")
    def about(request: Request):
        path = request.app.state.metrics_path
        if not path.exists():
            raise HTTPException(
                status_code=503,
                detail="metrics not yet produced — training has not run",
            )
        return json.loads(path.read_text())

    @app.get("/songs")
    def songs(conn: sqlite3.Connection = Depends(get_read)):  # noqa: B008
        rows = conn.execute(
            "SELECT song_id, name, original_artist, slug FROM songs ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    class NewSong(BaseModel):
        name: str

    @app.post("/songs", status_code=201)
    def insert_song(
        body: NewSong,
        response: Response,
        conn: sqlite3.Connection = Depends(get_rw),  # noqa: B008
    ):
        existing = conn.execute(
            "SELECT song_id, name, is_bustout_placeholder FROM songs WHERE name = ?",
            (body.name,),
        ).fetchone()
        if existing:
            response.status_code = 200
            return {
                "song_id": existing["song_id"],
                "name": existing["name"],
                "is_bustout_placeholder": bool(existing["is_bustout_placeholder"]),
            }
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        cur = conn.execute(
            "INSERT INTO songs (name, first_seen_at, is_bustout_placeholder) "
            "VALUES (?, ?, 1)",
            (body.name, now),
        )
        conn.commit()
        return {
            "song_id": cur.lastrowid,
            "name": body.name,
            "is_bustout_placeholder": True,
        }

    @app.get("/upcoming")
    def upcoming(
        request: Request,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
    ):
        # Compute "today" with a 15-hour lag so the rollover from one show
        # to the next happens the morning AFTER a show, not during it.
        # Plain UTC midnight = 5pm Pacific / 8pm Eastern, which is before
        # a typical 7pm-11pm show even starts — causing the next day's
        # show to appear "upcoming" while tonight's is still pending or
        # in progress. 15h shifts the rollover to 15:00 UTC = 8am PDT
        # / 11am EDT, comfortably after any US show has ended.
        today = (datetime.now(UTC) - timedelta(hours=15)).date().isoformat()
        shows = request.app.state.phishnet_client.fetch_upcoming_shows(today)
        if not shows:
            raise HTTPException(status_code=404, detail="no upcoming Phish shows")
        first = shows[0]
        state = first.get("state", "")
        show_id = int(first["showid"])
        # Residency-wide position: count all same-venue + same-tour shows
        # ("the 9-show 2026 Sphere residency"). NOT the same as the schema's
        # run_position/run_length, which scope to consecutive-day micro-runs
        # (a 9-show residency split by off-days has three 3-night sub-runs).
        # Suppressed for one-show "residencies" — no badge worth showing.
        run_position, run_length = _residency_position(read, show_id)
        return {
            "show_id": show_id,
            "show_date": first["showdate"],
            "venue": first.get("venue", ""),
            "city": first.get("city", ""),
            "state": state,
            "timezone": tz_for_state(state),
            "start_time_local": "19:00",
            "run_position": run_position,
            "run_length": run_length,
        }

    @app.get("/last-show")
    def last_show(read: sqlite3.Connection = Depends(get_read)):  # noqa: B008
        from phishpicker.last_show import resolve_last_show_id

        show_id = resolve_last_show_id(read)
        if show_id is None:
            raise HTTPException(404, "no completed shows")
        row = read.execute(
            """
            SELECT s.show_id, s.show_date, s.venue_id, v.name AS venue,
                   v.city, v.state
            FROM shows s LEFT JOIN venues v USING (venue_id)
            WHERE s.show_id = ?
            """,
            (show_id,),
        ).fetchone()
        run_position, run_length = _residency_position(read, show_id)
        return {
            "show_id": int(row["show_id"]),
            "show_date": row["show_date"],
            "venue": row["venue"] or "",
            "city": row["city"] or "",
            "state": row["state"] or "",
            "run_position": run_position,
            "run_length": run_length,
        }

    @app.get("/last-show/review")
    def last_show_review(
        request: Request,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
    ):
        from contextlib import closing

        from phishpicker.db.connection import open_db
        from phishpicker.last_show import resolve_last_show_id
        from phishpicker.slot_ranks import _SET_ORDER, compute_slot_ranks

        show_id = resolve_last_show_id(read)
        if show_id is None:
            raise HTTPException(404, "no completed shows")

        scorer = request.app.state.scorer
        model_sha = scorer.sha

        # Cache check: count must match setlist length AND map by slot_idx.
        cached = {
            r["slot_idx"]: (int(r["actual_song_id"]), r["actual_rank"])
            for r in read.execute(
                "SELECT slot_idx, actual_song_id, actual_rank "
                "FROM slot_predictions_cache WHERE show_id = ? AND model_sha = ?",
                (show_id, model_sha),
            ).fetchall()
        }
        setlist_count = read.execute(
            "SELECT COUNT(*) FROM setlist_songs WHERE show_id = ?",
            (show_id,),
        ).fetchone()[0]

        if len(cached) == setlist_count:
            # Cache hit. Reconstruct slot_idx → (set_number, position, song name)
            # by walking setlist_songs in the same canonical order the helper uses.
            raw = read.execute(
                "SELECT set_number, position, song_id FROM setlist_songs WHERE show_id = ?",
                (show_id,),
            ).fetchall()
            setlist = sorted(
                raw,
                key=lambda r: (
                    _SET_ORDER.get(str(r["set_number"]).upper(), 99),
                    int(r["position"]),
                ),
            )
            song_names = {
                r["song_id"]: r["name"]
                for r in read.execute("SELECT song_id, name FROM songs")
            }
            slots_out = []
            for idx, s in enumerate(setlist, start=1):
                rank_entry = cached.get(idx)
                actual_rank = rank_entry[1] if rank_entry else None
                slots_out.append({
                    "slot_idx": idx,
                    "set_number": s["set_number"],
                    "position": int(s["position"]),
                    "actual_song_id": int(s["song_id"]),
                    "actual_song": song_names.get(s["song_id"], f"#{s['song_id']}"),
                    "actual_rank": actual_rank,
                })
        else:
            # Cache miss — compute, write, and use in-memory results directly.
            ranks = compute_slot_ranks(read, show_id=show_id, scorer=scorer)
            now = datetime.now(UTC).isoformat()
            db_path = request.app.state.settings.db_path
            with closing(open_db(db_path, read_only=False)) as write:
                write.executemany(
                    "INSERT OR REPLACE INTO slot_predictions_cache "
                    "(show_id, model_sha, slot_idx, actual_song_id, actual_rank, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (show_id, model_sha, r.slot_idx, r.actual_song_id, r.actual_rank, now)
                        for r in ranks
                    ],
                )
                write.commit()
            song_names = {
                r["song_id"]: r["name"]
                for r in read.execute("SELECT song_id, name FROM songs")
            }
            slots_out = [
                {
                    "slot_idx": r.slot_idx,
                    "set_number": r.set_number,
                    "position": r.position,
                    "actual_song_id": r.actual_song_id,
                    "actual_song": song_names.get(r.actual_song_id, f"#{r.actual_song_id}"),
                    "actual_rank": r.actual_rank,
                }
                for r in ranks
            ]

        show_meta_row = read.execute(
            "SELECT s.show_id, s.show_date, s.venue_id, v.name AS venue, v.city, v.state "
            "FROM shows s LEFT JOIN venues v USING (venue_id) WHERE s.show_id = ?",
            (show_id,),
        ).fetchone()
        run_position, run_length = _residency_position(read, show_id)

        return {
            "show": {
                "show_id": int(show_meta_row["show_id"]),
                "show_date": show_meta_row["show_date"],
                "venue": show_meta_row["venue"] or "",
                "city": show_meta_row["city"] or "",
                "state": show_meta_row["state"] or "",
                "run_position": run_position,
                "run_length": run_length,
            },
            "slots": slots_out,
        }

    @app.post("/live/show")
    def create_show(body: LiveShowCreate, conn: sqlite3.Connection = Depends(get_live)):  # noqa: B008
        show_id = create_live_show(conn, body.show_date, body.venue_id)
        return {"show_id": show_id}

    @app.get("/live/show/{show_id}")
    def get_show(show_id: str, conn: sqlite3.Connection = Depends(get_live)):  # noqa: B008
        show = get_live_show(conn, show_id)
        if show is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="show not found")
        return show

    @app.post("/live/song")
    def add_song(body: LiveSongAppend, conn: sqlite3.Connection = Depends(get_live)):  # noqa: B008
        order = append_song(conn, body.show_id, body.song_id, body.set_number, body.trans_mark)
        return {"entered_order": order}

    @app.delete("/live/song/last")
    def undo_last(show_id: str, conn: sqlite3.Connection = Depends(get_live)):  # noqa: B008
        ok = delete_last_song(conn, show_id)
        return {"deleted": ok}

    @app.post("/live/set-boundary")
    def set_boundary(body: SetBoundary, conn: sqlite3.Connection = Depends(get_live)):  # noqa: B008
        ok = advance_set(conn, body.show_id, body.set_number)
        return {"updated": ok}

    @app.post("/internal/reload")
    def internal_reload(request: Request, x_admin_token: str = Header(None)):  # noqa: B008
        expected = request.app.state.settings.admin_token
        if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
            raise HTTPException(status_code=401, detail="invalid admin token")
        request.app.state.scorer = load_runtime_scorer(request.app.state.model_path)
        log.info("reloaded scorer: %s", request.app.state.scorer.name)
        return {"reloaded": True, "scorer": request.app.state.scorer.name}

    class PredictRequest(BaseModel):
        played_songs: list[int] = []
        current_set: str
        show_date: str
        venue_id: int | None = None
        prev_trans_mark: str = ","
        prev_set_number: str | None = None
        top_n: int = 20

    @app.post("/predict")
    def predict_post(
        body: PredictRequest,
        request: Request,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
    ):
        return {
            "candidates": predict_next_stateless(
                read_conn=read,
                scorer=request.app.state.scorer,
                **body.model_dump(),
            )
        }

    class StructureUpdate(BaseModel):
        set1: int = 9
        set2: int = 7
        encore: int = 2

    @app.post("/live/show/{show_id}/structure")
    def set_structure(
        show_id: str,
        body: StructureUpdate,
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        live.execute(
            "INSERT INTO live_show_meta (show_id, set1_size, set2_size, encore_size) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(show_id) DO UPDATE SET "
            "set1_size=excluded.set1_size, "
            "set2_size=excluded.set2_size, "
            "encore_size=excluded.encore_size",
            (show_id, body.set1, body.set2, body.encore),
        )
        live.commit()
        return {"ok": True}

    @app.get("/live/show/{show_id}/preview")
    def preview_endpoint(
        show_id: str,
        request: Request,
        top_k: int = 10,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        from phishpicker.live_preview import build_preview

        return build_preview(
            read_conn=read,
            live_conn=live,
            show_id=show_id,
            top_k=top_k,
            scorer=request.app.state.scorer,
        )

    class SyncStart(BaseModel):
        show_date: str

    @app.post("/live/show/{show_id}/sync/start")
    async def sync_start(show_id: str, body: SyncStart, request: Request):
        s = request.app.state.settings
        await request.app.state.pollers.start(
            show_id,
            show_date=body.show_date,
            interval=60.0,
            db_path=s.db_path,
            live_db_path=s.live_db_path,
            api_key=s.phishnet_api_key,
            scorer=request.app.state.scorer,
            vapid_private_key=s.vapid_private_key,
            vapid_subject=s.vapid_subject,
        )
        # Open our own connection: this async endpoint may run on a different
        # thread than whichever thread Depends(get_live) would have opened on.
        with closing(open_db(s.live_db_path)) as live:
            live.execute(
                "INSERT INTO live_show_meta (show_id, sync_enabled) VALUES (?, 1) "
                "ON CONFLICT(show_id) DO UPDATE SET sync_enabled=1",
                (show_id,),
            )
            live.commit()
        return {"started": True}

    @app.post("/live/show/{show_id}/sync/stop")
    async def sync_stop(show_id: str, request: Request):
        s = request.app.state.settings
        await request.app.state.pollers.stop(show_id)
        with closing(open_db(s.live_db_path)) as live:
            live.execute(
                "UPDATE live_show_meta SET sync_enabled=0 WHERE show_id = ?",
                (show_id,),
            )
            live.commit()
        return {"stopped": True}

    @app.post("/live/show/{show_id}/sync/now")
    async def sync_now(show_id: str, body: SyncStart, request: Request):
        """Fire an immediate sync pass, bypassing the 60s poller interval.
        Called by the web when the PWA returns to the foreground so the
        user sees the current setlist state without waiting for the next
        tick. Skips if sync is disabled — a backgrounded tab returning
        shouldn't reactivate sync that the user explicitly turned off.
        """
        from phishpicker.live_sync import sync_show_with_phishnet

        s = request.app.state.settings
        with closing(open_db(s.live_db_path)) as live:
            row = live.execute(
                "SELECT sync_enabled FROM live_show_meta WHERE show_id = ?",
                (show_id,),
            ).fetchone()
        if not row or not row["sync_enabled"]:
            return {"status": "skipped", "reason": "sync_disabled"}
        result = await asyncio.to_thread(
            sync_show_with_phishnet,
            db_path=s.db_path,
            live_db_path=s.live_db_path,
            api_key=s.phishnet_api_key,
            show_id=show_id,
            show_date=body.show_date,
            scorer=request.app.state.scorer,
            vapid_private_key=s.vapid_private_key,
            vapid_subject=s.vapid_subject,
        )
        return result

    @app.get("/live/show/{show_id}/sync/status")
    def sync_status(
        show_id: str,
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        row = live.execute(
            "SELECT sync_enabled, last_updated, last_error "
            "FROM live_show_meta WHERE show_id = ?",
            (show_id,),
        ).fetchone()
        if not row:
            return {
                "state": "off",
                "sync_enabled": False,
                "last_updated": None,
                "last_error": None,
            }
        state = "off"
        if row["sync_enabled"]:
            if row["last_updated"]:
                last = datetime.fromisoformat(
                    row["last_updated"].replace("Z", "+00:00")
                )
                age = (datetime.now(UTC) - last).total_seconds()
                if age < 120:
                    state = "live"
                elif age < 600:
                    state = "stale"
                else:
                    state = "dead"
            else:
                state = "stale"
            if row["last_error"]:
                state = "dead"
        return {
            "state": state,
            "sync_enabled": bool(row["sync_enabled"]),
            "last_updated": row["last_updated"],
            "last_error": row["last_error"],
        }

    @app.get("/live/show/{show_id}/slot/{slot_idx}/alternatives")
    def slot_alternatives(
        show_id: str,
        slot_idx: int,
        request: Request,
        top_k: int = 10,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        from phishpicker.live_preview import build_preview

        pr = build_preview(
            read_conn=read,
            live_conn=live,
            show_id=show_id,
            top_k=top_k,
            scorer=request.app.state.scorer,
        )
        if slot_idx < 1 or slot_idx > len(pr["slots"]):
            raise HTTPException(404, "slot out of range")
        return pr["slots"][slot_idx - 1]

    @app.get("/predict/{show_id}")
    def predict(
        show_id: str,
        request: Request,
        top_n: int = 20,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        return {
            "candidates": predict_next(
                read, live, show_id, top_n=top_n, scorer=request.app.state.scorer
            )
        }

    # ---- Web Push / VAPID --------------------------------------------------

    class PushSubscribeBody(BaseModel):
        endpoint: str
        keys: dict  # {"p256dh": "...", "auth": "..."}

    @app.get("/push/vapid-key")
    def push_vapid_key(request: Request):
        """Return the VAPID public key the client uses in pushManager.subscribe().
        Empty string signals push is disabled on this server."""
        return {"key": request.app.state.settings.vapid_public_key}

    @app.post("/push/subscribe")
    def push_subscribe(
        body: PushSubscribeBody,
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        from phishpicker.push import save_subscription

        p256dh = body.keys.get("p256dh")
        auth = body.keys.get("auth")
        if not p256dh or not auth:
            raise HTTPException(400, "subscription keys missing p256dh or auth")
        save_subscription(live, body.endpoint, p256dh, auth)
        return {"ok": True}

    @app.delete("/push/subscribe")
    def push_unsubscribe(
        body: dict,
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        from phishpicker.push import delete_subscription

        endpoint = body.get("endpoint")
        if not endpoint:
            raise HTTPException(400, "endpoint required")
        deleted = delete_subscription(live, endpoint)
        return {"deleted": deleted}

    return app
