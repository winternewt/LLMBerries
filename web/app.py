"""Builds the FastAPI app: API routers plus the static face.

`create_app(runs_root=...)` takes the archive location so tests can point it at a
temporary directory; the default is the same `runs/` the CLI writes.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web import runs

STATIC_DIR = Path(__file__).parent / "static"


def create_app(runs_root: Path = Path("runs")) -> FastAPI:
    app = FastAPI(title="LLMBerries observatory", docs_url=None, redoc_url=None)
    app.state.runs_root = runs_root
    app.state.snapshots = runs.SnapshotCache()
    app.include_router(runs.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
