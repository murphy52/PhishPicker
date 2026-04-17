import hmac
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
from phishpicker.predict import predict_next


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


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        yield

    app = FastAPI(title="Phishpicker", lifespan=lifespan)
    get_read = _read_conn_dep(settings)
    get_live = _live_conn_dep(settings)
    # Expose dependency factories on app.state so endpoints in other modules
    # can access them via request.app.state.
    app.state.get_read = get_read
    app.state.get_live = get_live

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
    def meta(conn: sqlite3.Connection = Depends(get_read)):  # noqa: B008
        shows = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
        songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        latest = conn.execute("SELECT MAX(show_date) FROM shows").fetchone()[0]
        return {
            "shows_count": shows,
            "songs_count": songs,
            "latest_show_date": latest,
            "data_snapshot_at": datetime.now(UTC).isoformat(),
            "version": "0.1.0-skeleton",
        }

    @app.get("/songs")
    def songs(conn: sqlite3.Connection = Depends(get_read)):  # noqa: B008
        rows = conn.execute("SELECT song_id, name, original_artist FROM songs ORDER BY name").fetchall()
        return [dict(r) for r in rows]

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
        return {"reloaded": True}

    @app.get("/predict/{show_id}")
    def predict(
        show_id: str,
        top_n: int = 20,
        read: sqlite3.Connection = Depends(get_read),  # noqa: B008
        live: sqlite3.Connection = Depends(get_live),  # noqa: B008
    ):
        return {"candidates": predict_next(read, live, show_id, top_n=top_n)}

    return app
