"""FastAPI app factory + lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lorscan.app.routes import scan
from lorscan.config import Config, load_config
from lorscan.storage.db import Database

_PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(_PACKAGE_DIR / "templates"))


def create_app(config: Config | None = None) -> FastAPI:
    """Build a configured FastAPI app. Pass `config` for tests; otherwise loads from env."""
    cfg = config if config is not None else load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Ensure data dir exists and migrations are applied.
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cfg.photos_dir.mkdir(parents=True, exist_ok=True)
        db = Database.connect(str(cfg.db_path))
        db.migrate()
        db.close()
        yield

    app = FastAPI(
        title="lorscan",
        description="Lorcana collection manager — local web UI",
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.templates = TEMPLATES

    app.mount(
        "/static",
        StaticFiles(directory=str(_PACKAGE_DIR / "static")),
        name="static",
    )

    app.include_router(scan.router)
    return app
