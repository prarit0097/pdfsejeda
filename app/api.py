"""/api/* routes. Contract mirrors research/SEJDA.md (see sejedarules.md §5)."""
from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .config import settings
from .jobs import TaskError, queue
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
    size = 0
    with open(f.path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_file_bytes:
                out.close()
                files.delete(f.id)
                return _bad(f"File is too large. The limit is {settings.max_file_mb} MB.", 413)
            out.write(chunk)
    return _file_info(files.finalize(f))


@router.post("/files/upload-chunked")
async def upload_chunked(file: UploadFile = File(...), content_range: str = Header(...),
                         x_upload_id: str = Header(...), x_file_name: str = Header("")):
    """Chunked upload: each request carries `Content-Range: bytes start-end/total`.

    The last chunk returns the file info; earlier chunks return {"status": "partial", "received": n}.
    """
    m = re.match(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
    if not m or not _UPLOAD_ID.match(x_upload_id):
        return _bad("Invalid chunk headers")
    start, end, total = (int(g) for g in m.groups())
    if total > settings.max_file_bytes:
        return _bad(f"File is too large. The limit is {settings.max_file_mb} MB.", 413)
    part_dir = settings.uploads_dir / f".chunks-{x_upload_id}"
    part_dir.mkdir(exist_ok=True)
    part = part_dir / "data"
    data = await file.read()
    if len(data) != end - start + 1:
        return _bad("Chunk size does not match Content-Range")
    with open(part, "r+b" if part.exists() else "wb") as out:
        out.seek(start)
        out.write(data)
    received = part.stat().st_size
    if end + 1 < total or received < total:
        return {"status": "partial", "received": received}
    name = unquote(x_file_name) or file.filename or "file"
    f = files.create_empty(name, mimetypes.guess_type(name)[0] or "application/octet-stream")
    shutil.move(str(part), f.path)
    shutil.rmtree(part_dir, ignore_errors=True)
    return _file_info(files.finalize(f))


@router.post("/files")
async def import_url(request: Request):
    body = await request.json()
    url = str(body.get("url", "")).strip()
    if not url:
        return _bad("Please enter a web address")
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
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
    f.mime = ctype
    if "." not in f.name:
        ext = mimetypes.guess_extension(ctype) or ""
        f.name += ".pdf" if ctype == "application/pdf" else ext
    return _file_info(files.finalize(f))


@router.post("/files/{file_id}/password")
async def set_password(file_id: str, request: Request):
    import pikepdf

    body = await request.json()
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
    return FileResponse(f.path, media_type=f.mime if f.mime != "application/octet-stream" else "application/pdf",
                        headers={"Cache-Control": "no-store, private", "Content-Disposition": "inline"})


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
    except (FileNotFound, TaskError) as e:
        return _bad(str(e) or "File not found", 404)


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
    except (FileNotFound, TaskError) as e:
        return _bad(str(e) or "File not found", 404)


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
        body = await request.json()
    except Exception:
        return _bad("Invalid request")
    if not isinstance(body, dict):
        return _bad("Invalid request")
    task_type = str(body.get("type", ""))
    file_ids = body.get("files") or []
    if isinstance(file_ids, str):
        file_ids = [file_ids]
    file_ids = [str(x) for x in file_ids if x]
    params = {k: v for k, v in body.items() if k not in _IGNORED_FIELDS and k not in ("type", "files")}
    from .tools.registry import get_tool

    try:
        get_tool(task_type)
    except KeyError:
        return _bad(f"Unknown task type '{task_type}'")
    if not file_ids and task_type not in ("htmlToPdf",):
        return _bad("Please add a file first")
    allowed, remaining, wait = quota.consume(client_ip(request))
    if not allowed:
        return JSONResponse({"reason": "tasks-per-hour", "code": "tasks-per-hour"}, status_code=402,
                            headers={"x-ratelimit-remaining": "-1", "x-ratelimit-wait": str(wait)})
    try:
        task = queue.submit(task_type, file_ids, params)
    except FileNotFound:
        return _bad("File not found. Please upload it again and retry.")
    except TaskError as e:
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
        out.update({
            "resultFilename": task.result_filename,
            "resultFileSize": (task.out_dir / task.result_filename).stat().st_size,
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
    name = Path(unquote(filename)).name
    path = task.out_dir / name
    if not path.is_file():  # renamed download: serve the main result under the requested name
        path = task.out_dir / task.result_filename
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    disp = "attachment" if d == "true" and v != "true" else "inline"
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
    out = []
    for n in names:
        p = task.out_dir / n
        f = files.create_empty(n, mimetypes.guess_type(n)[0] or "application/octet-stream")
        shutil.copyfile(p, f.path)
        out.append(_file_info(files.finalize(f)))
    return out


@router.get("/tools")
async def tools_catalog():
    from .tools.registry import all_tools

    return [{"type": t.type, "slug": t.slug, "title": t.title, "tagline": t.tagline, "category": t.category,
             "accept": t.accept, "multiple": t.multiple, "options": [o.__dict__ for o in t.options]}
            for t in all_tools()]
