"""Local-only preview API and narrowly scoped static frontend serving."""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

from airspace_monitor.preview import read_preview


def create_app(recording: Path | None, web_dir: Path) -> FastAPI:
    app = FastAPI(title="Hungarian Airspace — local preview", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "mode": "local-preview"}

    @app.get("/api/preview")
    def preview(response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            return read_preview(recording)
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, "The local recording cannot be read.") from None

    # Only built public assets are exposed; the repository and recordings are never mounted.
    app.mount("/", StaticFiles(directory=web_dir, html=True, follow_symlink=False), name="web")
    return app
