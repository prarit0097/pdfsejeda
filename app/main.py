"""FastAPI application: static files, HTML pages, /api, background cleanup."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import api, web
from .config import settings
from .jobs import queue
from .ratelimit import quota
from .storage import files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BASE = Path(__file__).resolve().parent


def sweep_once() -> int:
    """Delete expired uploads, tasks and result folders. Returns the number of removed uploads."""
    import shutil
    import time

    removed = files.sweep()
    queue.sweep()
    quota.prune()
    cutoff = time.time() - settings.file_ttl_seconds
    for d in list(settings.results_dir.iterdir()):  # result folders of tasks no longer in memory
        try:
            if d.stat().st_mtime < cutoff and not queue.get(d.name.split(".")[0]):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue
    if removed:
        logging.getLogger("sweeper").info("removed %d expired uploads", removed)
    return removed


def sweep_interval() -> float:
    """Every 5 minutes, or more often when the TTL is short (so files never outlive it by much)."""
    return max(1.0, min(300.0, settings.file_ttl_seconds / 4))


async def _sweeper():
    while True:
        await asyncio.sleep(sweep_interval())
        try:
            await asyncio.to_thread(sweep_once)
        except Exception:  # keep sweeping whatever happens
            logging.getLogger("sweeper").exception("sweep failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",  # PDF.js codecs use WASM; JavaScript eval remains blocked
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])

_MB = 1024 * 1024


def _body_limit(path: str) -> int:
    if path == "/api/files/upload":
        return settings.max_file_bytes + _MB  # multipart overhead
    if path == "/api/files/upload-chunked":
        return settings.max_chunk_bytes + _MB
    return settings.max_request_mb * _MB


class BodySizeLimit:
    """Reject request bodies over the limit *while they stream in* (before Starlette spools a
    huge multipart upload to a temp file). Content-Length is checked up front; chunked bodies
    are counted. Answers 413."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = _body_limit(scope["path"])
        msg = "Request is too large." if not scope["path"].startswith("/api/files/upload") else             f"File is too large. The limit is {settings.max_file_mb} MB."
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limit:
                        return await PlainTextResponse(msg, status_code=413)(scope, receive, send)
                except ValueError:
                    return await PlainTextResponse("Bad Content-Length", status_code=400)(scope, receive, send)
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    from fastapi import HTTPException

                    raise HTTPException(413, msg)
            return message

        return await self.app(scope, limited_receive, send)

app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)


@app.exception_handler(api._BadBody)
async def _bad_body(request: Request, exc: Exception):
    return PlainTextResponse("Invalid request", status_code=400)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """Pages get the HTML 404 page; the API and static files keep FastAPI's JSON errors."""
    path = request.url.path
    if exc.status_code == 404 and request.method in ("GET", "HEAD") and not path.startswith(("/api/", "/static/")):
        return web._render(request, "404.html", status=404)
    return await http_exception_handler(request, exc)


app.add_middleware(BodySizeLimit)  # added before security_headers -> runs inside it (its errors stay plain HTTPExceptions)


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
        if response.headers.get("content-type", "").startswith("text/html"):
            h.setdefault("Content-Security-Policy", CSP)
    return response


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(api.router)
app.include_router(web.router)
