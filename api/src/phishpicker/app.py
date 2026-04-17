import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime

from fastapi import Depends, FastAPI

from phishpicker.config import Settings
from phishpicker.db.connection import open_db


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

    return app
