"""/api/* routes. Contract mirrors research/SEJDA.md (see sejedarules.md §5)."""
from __future__ import annotations

import json
import mimetypes
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .config import settings
from .jobs import QueueFull, TaskError, queue
from .ratelimit import quota
from .security import UnsafeUrl, check_signature, fetch_url, sign_task
from .storage import FileNotFound, files, safe_filename

router = APIRouter(prefix="/api")

# Fields the browser may add that are not tool options (Sejda sends similar telemetry).
_IGNORED_FIELDS = {"uri", "userAgent", "cvts", "pdfjs", "libsCache", "consoleLogs", "traceId", "www", "ipclient",
                   "promo", "captchaToken", "elapsedTime", "recovered", "workflowId", "workflowStep"}
_UPLOAD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        for h in ("cf-connecting-ip", "x-real-ip"):
            if request.headers.get(h):
                return request.headers[h]
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bad(msg: str, status: int = 400):
    return PlainTextResponse(msg, status_code=status)


class _BadBody(Exception):
    pass


async def _json_object(request: Request) -> dict:
    """The request body as a JSON object, or _BadBody (-> 400) for anything else."""
    try:
        body = await request.json()
    except HTTPException:
        raise
    except Exception:
        raise _BadBody() from None
    if not isinstance(body, dict):
        raise _BadBody()
    return body


# Types the browser may render as active content on our origin: always served as a download.
_ACTIVE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml",
                 "text/javascript", "application/javascript", "application/x-javascript", "text/css"}
# Types that are fine to show inline (preview iframe, thumbnails).
_INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
                 "image/tiff", "text/plain", "text/csv"}


def _safe_media(name: str, fallback: str | None = None) -> tuple[str, bool]:
    """(content type, may be inline) for serving a stored file named `name`."""
    media = mimetypes.guess_type(name)[0] or fallback or "application/octet-stream"
    media = media.split(";")[0].strip().lower()
    if media in _ACTIVE_TYPES:
        return "application/octet-stream", False
    if media.startswith("text/"):
        media += "; charset=utf-8"
    return media, media.split(";")[0] in _INLINE_TYPES


def _file_info(f) -> dict:
    info = {"id": f.id, "name": f.name, "size": f.size, "pages": None, "passwordProtected": False}
    if f.name.lower().endswith(".pdf") or f.mime == "application/pdf":
        import pikepdf

        try:
            with pikepdf.open(f.path, password=f.password or "") as pdf:
                info["pages"] = len(pdf.pages)
        except pikepdf.PasswordError:
            info["passwordProtected"] = True
        except Exception:
            info["damaged"] = True
    return info


# ---- files ---------------------------------------------------------------


@router.post("/files/upload-check")
async def upload_check():
    return {"status": "ok"}


@router.post("/files/upload")
async def upload(file: UploadFile = File(...)):
    f = files.create_empty(file.filename or "file", file.content_type or "application/octet-stream")
    complete = False
    try:
        size = 0
        with open(f.path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_bytes:
                    return _bad(f"File is too large. The limit is {settings.max_file_mb} MB.", 413)
                out.write(chunk)
        info = _file_info(files.finalize(f))
        complete = True
        return info
    finally:
        if not complete:
            files.delete(f.id)
        await file.close()


@router.post("/files/upload-chunked")
async def upload_chunked(file: UploadFile = File(...), content_range: str = Header(...),
                         x_upload_id: str = Header(...), x_file_name: str = Header("")):
    """Chunked upload: each request carries `Content-Range: bytes start-end/total`.

    The last chunk returns the file info; earlier chunks return {"status": "partial", "received": n}.
    """
    m = re.fullmatch(r"bytes (\d{1,15})-(\d{1,15})/(\d{1,15})", (content_range or "").strip())
    if not m or not _UPLOAD_ID.match(x_upload_id or ""):
        return _bad("Invalid chunk headers")
    start, end, total = (int(g) for g in m.groups())
    if total > settings.max_file_bytes:
        return _bad(f"File is too large. The limit is {settings.max_file_mb} MB.", 413)
    if not (0 <= start <= end < total):
        return _bad("Invalid Content-Range")
    if end - start + 1 > settings.max_chunk_bytes:
        return _bad("Chunk is too large", 413)
    data = await file.read(settings.max_chunk_bytes + 1)
    if len(data) != end - start + 1:
        return _bad("Chunk size does not match Content-Range")
    # No await below this line: chunks of one upload are applied one at a time (single event loop).
    part_dir = settings.uploads_dir / f".chunks-{x_upload_id}"
    part_dir.mkdir(exist_ok=True)
    part, state_file = part_dir / "data", part_dir / "ranges.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"total": total, "ranges": []}
    if state.get("total") != total:
        return _bad("Content-Range total does not match the earlier chunks")
    with open(part, "r+b" if part.exists() else "wb") as out:
        out.seek(start)
        out.write(data)
    ranges = sorted(state["ranges"] + [[start, end]])
    merged: list[list[int]] = []
    for a, b in ranges:  # merge overlapping/adjacent ranges; overlaps are counted once
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    received = sum(b - a + 1 for a, b in merged)
    if received < total:
        state_file.write_text(json.dumps({"total": total, "ranges": merged}), encoding="utf-8")
        return {"status": "partial", "received": received}
    name = unquote(x_file_name or "") or file.filename or "file"
    f = files.create_empty(name, mimetypes.guess_type(name)[0] or "application/octet-stream")
    shutil.move(str(part), f.path)
    shutil.rmtree(part_dir, ignore_errors=True)
    with open(f.path, "r+b") as out:  # a chunk may have been resent past the end: never keep extra bytes
        out.truncate(total)
    return _file_info(files.finalize(f))


@router.post("/files")
async def import_url(request: Request):
    body = await _json_object(request)
    url = str(body.get("url", "")).strip()
    if not url:
        return _bad("Please enter a web address")
    if "://" not in url:
        url = "https://" + url
    try:
        p = urlparse(url)
        p.port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        return _bad("That doesn't look like a valid web address")
    if p.scheme not in ("http", "https") or not p.hostname:
        return _bad("Only http and https links are supported")
    name = safe_filename(unquote(Path(p.path).name) or p.hostname or "file", "file")
    if body.get("originalFilename"):
        name = safe_filename(str(body["originalFilename"]))
    f = files.create_empty(name, source_url=url)
    try:
        with open(f.path, "wb") as out:
            import anyio

            _, ctype = await anyio.to_thread.run_sync(fetch_url, url, out, settings.max_file_bytes)
    except UnsafeUrl as e:
        files.delete(f.id)
        return _bad(str(e))
    except Exception:
        files.delete(f.id)
        return _bad("Could not download the file from that address")
    f.mime = ctype if re.fullmatch(r"[\w.+-]+/[\w.+-]+", ctype or "") else "application/octet-stream"
    if "." not in f.name:
        ext = mimetypes.guess_extension(ctype) or ""
        f.name += ".pdf" if ctype == "application/pdf" else ext
    return _file_info(files.finalize(f))


@router.post("/files/{file_id}/password")
async def set_password(file_id: str, request: Request):
    import pikepdf

    body = await _json_object(request)
    password = str(body.get("password", ""))
    try:
        f = files.get(file_id)
    except FileNotFound:
        return _bad("File not found", 404)
    try:
        with pikepdf.open(f.path, password=password) as pdf:
            pages = len(pdf.pages)
    except pikepdf.PasswordError:
        return _bad("Incorrect password")
    except Exception:
        return _bad("Could not open this PDF")
    files.set_password(file_id, password)
    return {"status": "ok", "pages": pages}


@router.post("/files/{file_id}/touch")
async def touch(file_id: str):
    try:
        files.touch(file_id)
    except FileNotFound:
        return _bad("File not found", 404)
    return {"status": "ok"}


@router.get("/files/{file_id}/view")
async def view_file(file_id: str):
    try:
        f = files.get(file_id)
    except FileNotFound:
        return _bad("File not found", 404)
    guessed = (mimetypes.guess_type(f.name)[0] or f.mime or "").lower()
    if guessed in _ACTIVE_TYPES:  # never render uploaded HTML/SVG/JS on our origin
        media, inline = "application/octet-stream", False
    elif guessed in ("", "application/octet-stream"):  # unknown type (e.g. link without extension): PDF viewers sniff it
        media, inline = "application/pdf", True
    else:
        media, inline = _safe_media(f.name, f.mime)
    disp = "inline" if inline else f"attachment; filename*=UTF-8''{quote(f.name)}"
    return FileResponse(f.path, media_type=media, headers={"Cache-Control": "no-store, private", "Content-Disposition": disp})


@router.get("/files/{file_id}/outline")
async def file_outline(file_id: str):
    """Bookmarks as editable text ('Title | page', indented) for the bookmarks tool."""
    from .tools.common import open_pdf
    from .tools.outlines import read_outline
    from .tools.security_tools import outline_to_text
    from .jobs import InputFile

    try:
        f = files.get(file_id)
        with open_pdf(InputFile(f.id, f.name, f.path, f.password)) as pdf:
            return {"text": outline_to_text(read_outline(pdf)), "pages": len(pdf.pages)}
    except FileNotFound:
        return _bad("File not found", 404)
    except TaskError as e:
        return _bad(str(e), 400)


@router.get("/files/{file_id}/metadata")
async def file_metadata(file_id: str):
    from .tools.common import open_pdf
    from .jobs import InputFile

    try:
        f = files.get(file_id)
        with open_pdf(InputFile(f.id, f.name, f.path, f.password)) as pdf:
            out = {}
            for k in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate"):
                v = pdf.docinfo.get("/" + k)
                if v is None:
                    continue
                s = str(v)
                m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", s)
                if k.endswith("Date") and m:
                    s = f"{m[1]}-{m[2]}-{m[3]} {m[4] or '00'}:{m[5] or '00'}"
                out[k] = s
            return out
    except FileNotFound:
        return _bad("File not found", 404)
    except TaskError as e:
        return _bad(str(e), 400)


@router.get("/files/{file_id}")
async def file_info(file_id: str):
    try:
        return _file_info(files.get(file_id))
    except FileNotFound:
        return _bad("File not found", 404)


# ---- tasks ---------------------------------------------------------------


@router.post("/tasks")
async def create_task(request: Request):
    try:
        body = await _json_object(request)
    except _BadBody:
        return _bad("Invalid request")
    task_type = str(body.get("type", ""))
    file_ids = body.get("files") or []
    if isinstance(file_ids, str):
        file_ids = [file_ids]
    if not isinstance(file_ids, list) or not all(isinstance(x, str) for x in file_ids):
        return _bad("Invalid file list")
    file_ids = [x for x in file_ids if x]
    params = {k: v for k, v in body.items() if k not in _IGNORED_FIELDS and k not in ("type", "files")}
    from .tools.registry import get_tool

    try:
        get_tool(task_type)
    except KeyError:
        return _bad(f"Unknown task type '{task_type}'")
    if not file_ids and task_type not in ("htmlToPdf",):
        return _bad("Please add a file first")
    ip = client_ip(request)
    allowed, remaining, wait = quota.consume(ip)
    if not allowed:
        return JSONResponse({"reason": "tasks-per-hour", "code": "tasks-per-hour"}, status_code=402,
                            headers={"x-ratelimit-remaining": "-1", "x-ratelimit-wait": str(wait)})
    try:
        task = queue.submit(task_type, file_ids, params)
    except FileNotFound:
        quota.refund(ip)  # a rejected task doesn't count against the hourly quota
        return _bad("File not found. Please upload it again and retry.")
    except QueueFull as e:
        quota.refund(ip)
        return PlainTextResponse(str(e), status_code=429, headers={"Retry-After": "5"})
    except TaskError as e:
        quota.refund(ip)
        return _bad(str(e))
    return JSONResponse(task.id, headers={"x-ratelimit-remaining": str(remaining), "x-ratelimit-wait": str(wait)})


def _task_or_404(task_id: str):
    task = queue.get(task_id)
    if not task:
        return None
    return task


@router.get("/tasks/{task_id}/change")
async def task_change(task_id: str, request: Request):
    task = _task_or_404(task_id)
    if not task:
        return _bad("Task not found or expired", 404)
    out = {"id": task.id, "status": task.status, "type": task.type, "warnings": task.warnings}
    if task.remark:
        out["remark"] = task.remark
    if task.status == "Completed":
        sig = sign_task(task.id)
        host = request.url.netloc
        try:
            size = (task.out_dir / task.result_filename).stat().st_size
        except OSError:  # result removed from disk: same as expired
            return _bad("Task not found or expired", 404)
        out.update({
            "resultFilename": task.result_filename,
            "resultFileSize": size,
            "resultItems": task.result_items,
            "resultFullUrlPattern": f"{host}/api/tasks/{task.id}/download/%7B%7Bfilename%7D%7D?s={sig}&d=true",
        })
    if task.status == "Failed":
        out["failureReason"] = task.failure_reason
    return out


@router.get("/tasks/{task_id}/download/{filename}")
async def download(task_id: str, filename: str, s: str | None = None, d: str | None = None, v: str | None = None):
    task = _task_or_404(task_id)
    if not task or task.status != "Completed":
        return _bad("These files have expired", 404)
    if not check_signature(task.id, s):
        return _bad("Invalid download link", 403)
    name = safe_filename(Path(unquote(filename).replace("\\", "/")).name, task.result_filename)
    path = task.out_dir / name
    if name not in task.result_items and name != task.result_filename:
        path = task.out_dir / task.result_filename  # renamed download: serve the main result under the requested name
    if not path.is_file():
        return _bad("These files have expired", 404)
    media, inline = _safe_media(path.name)
    disp = "inline" if (v == "true" or d != "true") and inline else "attachment"
    return FileResponse(path, media_type=media, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store, private",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
    })


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: str):
    if not queue.cancel(task_id):
        return _bad("Task not found", 404)
    return {"status": "ok"}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    queue.delete(task_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/continue")
async def continue_with(task_id: str):
    """Register a task's result files as new uploads so another tool can use them."""
    task = _task_or_404(task_id)
    if not task or task.status != "Completed":
        return _bad("These files have expired", 404)
    names = [n for n in task.result_items] or [task.result_filename]
    out, created = [], []
    try:
        for n in names:
            p = task.out_dir / n
            if not p.is_file():
                raise OSError("Expired result")
            f = files.create_empty(n, mimetypes.guess_type(n)[0] or "application/octet-stream")
            created.append(f.id)
            shutil.copyfile(p, f.path)
            out.append(_file_info(files.finalize(f)))
    except OSError:
        for fid in created:
            files.delete(fid)
        return _bad("These files have expired", 404)
    return out


@router.get("/tools")
async def tools_catalog():
    from .tools.registry import all_tools

    return [{"type": t.type, "slug": t.slug, "title": t.title, "tagline": t.tagline, "category": t.category,
             "accept": t.accept, "multiple": t.multiple, "options": [o.__dict__ for o in t.options]}
            for t in all_tools()]
