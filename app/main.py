"""FastAPI application: static files, HTML pages, /api, background cleanup."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import api, web
from .config import settings
from .jobs import queue
from .storage import files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BASE = Path(__file__).resolve().parent


async def _sweeper():
    while True:
        await asyncio.sleep(300)
        with contextlib.suppress(Exception):
            removed = files.sweep()
            queue.sweep()
            import shutil
            import time

            for d in settings.results_dir.iterdir():  # result folders of tasks no longer in memory
                if time.time() - d.stat().st_mtime > settings.file_ttl_seconds and not queue.get(d.name.split(".")[0]):
                    shutil.rmtree(d, ignore_errors=True)
            if removed:
                logging.getLogger("sweeper").info("removed %d expired uploads", removed)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "interest-cohort=()")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store, private")
        if "/download/" not in request.url.path and "/view" not in request.url.path:
            h.setdefault("X-Frame-Options", "SAMEORIGIN")
    else:
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(api.router)
app.include_router(web.router)
