"""Builds the FastAPI app: API routers plus the static face.

`create_app(runs_root=...)` takes the archive location so tests can point it at a
temporary directory; the default is the same `runs/` the CLI writes.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web import live, runs

STATIC_DIR = Path(__file__).parent / "static"


def create_app(runs_root: Path = Path("runs")) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Server going down: ask a running game to stop and give it a moment to
        # seal its artifacts — the session log keeps everything up to a hard kill.
        app.state.games.shutdown()

    app = FastAPI(title="LLMBerries observatory", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.runs_root = runs_root
    app.state.snapshots = runs.SnapshotCache()
    app.state.games = live.LiveGameManager(runs_root)
    app.include_router(runs.router)
    app.include_router(live.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
