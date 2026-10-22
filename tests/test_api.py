"""End-to-end API flow: upload -> task -> poll -> download, plus errors."""
import time

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from conftest import make_pdf

client = TestClient(app)


def _upload(data=None, name="doc.pdf"):
    r = client.post("/api/files/upload", files={"file": (name, data or make_pdf(3), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def _wait(task_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/tasks/{task_id}/change")
        assert r.status_code == 200
        t = r.json()
        if t["status"] in ("Completed", "Failed"):
            return t
        time.sleep(0.1)
    raise AssertionError("task did not finish")


def test_pages_render():
    assert client.get("/").status_code == 200
    r = client.get("/merge-pdf")
    assert r.status_code == 200 and "Merge PDF" in r.text
    assert client.get("/no-such-tool").status_code == 404
    assert client.get("/privacy").status_code == 200


def test_full_flow():
    info = _upload()
    assert info["pages"] == 3 and not info["passwordProtected"]
    r = client.post("/api/tasks", json={"type": "extractPages", "files": [info["id"]], "pages": "1-2", "uri": "/x", "userAgent": "t"})
    assert r.status_code == 200, r.text
    task_id = r.json()
    assert "-" in task_id
    t = _wait(task_id)
    assert t["status"] == "Completed", t
    url = t["resultFullUrlPattern"].replace("%7B%7Bfilename%7D%7D", t["resultFilename"])
    path = url.split("/", 1)[1]
    d = client.get("/" + path)
    assert d.status_code == 200 and d.content.startswith(b"%PDF")
    assert "attachment" in d.headers["content-disposition"]
    bad = client.get("/" + path.replace("s=web-", "s=web-x"))
    assert bad.status_code == 403
    cont = client.post(f"/api/tasks/{task_id}/continue")
    assert cont.status_code == 200 and cont.json()[0]["pages"] == 2


def test_chunked_upload():
    data = make_pdf(2)
    half = len(data) // 2
    headers = {"X-Upload-Id": "abcdefgh1234", "X-File-Name": "big.pdf"}
    r1 = client.post("/api/files/upload-chunked", files={"file": ("big.pdf", data[:half])},
                     headers={**headers, "Content-Range": f"bytes 0-{half - 1}/{len(data)}"})
    assert r1.json()["status"] == "partial"
    r2 = client.post("/api/files/upload-chunked", files={"file": ("big.pdf", data[half:])},
                     headers={**headers, "Content-Range": f"bytes {half}-{len(data) - 1}/{len(data)}"})
    assert r2.json()["pages"] == 2


def test_errors_and_quota():
    assert client.post("/api/tasks", json={"type": "nope", "files": ["x"]}).status_code == 400
    assert client.post("/api/tasks", json={"type": "merge", "files": []}).status_code == 400
    info = _upload()
    t = _wait(client.post("/api/tasks", json={"type": "deletePages", "files": [info["id"]], "pages": "1-3"}).json())
    assert t["status"] == "Failed" and "every page" in t["failureReason"]
    old = settings.tasks_per_hour
    settings.tasks_per_hour = 1
    try:
        from app.ratelimit import quota

        quota._hits.clear()
        ok = client.post("/api/tasks", json={"type": "extractPages", "files": [info["id"]], "pages": "1"})
        assert ok.status_code == 200 and ok.headers["x-ratelimit-remaining"] == "0"
        over = client.post("/api/tasks", json={"type": "extractPages", "files": [info["id"]], "pages": "1"})
        assert over.status_code == 402 and over.json()["reason"] == "tasks-per-hour"
    finally:
        settings.tasks_per_hour = old


def test_url_import_blocks_private_hosts():
    r = client.post("/api/files", json={"url": "http://127.0.0.1/secret.pdf"})
    assert r.status_code == 400 and "private" in r.text.lower()


def test_bad_json_and_body_size_limits(monkeypatch):
    for body in ("[]", "null", "{broken"):
        assert client.post("/api/files", content=body, headers={"Content-Type": "application/json"}).status_code == 400
    monkeypatch.setattr(settings, "max_request_mb", 0)
    assert client.post("/api/tasks", content=b"{}", headers={"Content-Length": "2"}).status_code == 413
    def streamed():
        yield b"{"
        yield b"}"
    assert client.post("/api/tasks", content=streamed()).status_code == 413


def test_oversize_upload_removes_incomplete_file(monkeypatch):
    from app.storage import files
    before = set(files.root.iterdir())
    monkeypatch.setattr(settings, "max_file_mb", 0)
    response = client.post("/api/files/upload", files={"file": ("large.pdf", b"test", "application/pdf")})
    assert response.status_code == 413
    assert set(files.root.iterdir()) == before


def test_chunk_retries_and_holes_do_not_finalize_early():
    import uuid
    data = make_pdf(1)
    total = len(data)
    headers = {"X-Upload-Id": uuid.uuid4().hex, "X-File-Name": "retry.pdf"}
    def send(start, end, payload=None, advertised_total=None):
        return client.post("/api/files/upload-chunked", files={"file": ("retry.pdf", data[start:end + 1] if payload is None else payload)},
                           headers={**headers, "Content-Range": f"bytes {start}-{end}/{advertised_total or total}"})
    assert send(0, 99).json()["received"] == 100
    assert send(0, 99).json()["received"] == 100
    assert send(50, 149).json()["received"] == 150
    assert send(200, total - 1).json()["status"] == "partial"
    assert send(150, 199, advertised_total=total + 1).status_code == 400
    assert send(150, 199, payload=b"short").status_code == 400
    finished = send(150, 199)
    assert finished.status_code == 200 and finished.json()["pages"] == 1
    assert client.get(f"/api/files/{finished.json()['id']}/view").content == data
    traversal = client.post("/api/files/upload-chunked", files={"file": ("retry.pdf", b"a")},
                            headers={"X-Upload-Id": "../escape", "Content-Range": "bytes 0-0/2"})
    assert traversal.status_code == 400


def test_queue_busy_has_retry_and_refunds_quota(monkeypatch):
    from app.api import queue
    from app.jobs import QueueFull
    from app.ratelimit import quota
    info = _upload()
    monkeypatch.setattr(settings, "tasks_per_hour", 1)
    quota._hits.clear()
    def busy(*args, **kwargs):
        raise QueueFull("Server busy")
    monkeypatch.setattr(queue, "submit", busy)
    for _ in range(2):
        response = client.post("/api/tasks", json={"type": "extractPages", "files": [info["id"]]})
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
    assert not quota._hits.get("testclient")


def test_continue_rolls_back_copies_when_result_expired():
    from app.jobs import Task, new_task_id, queue
    from app.storage import files
    task = Task(new_task_id(), "splitByPages", {}, [], status="Completed", finished=time.time(),
                result_filename="all.zip", result_items=["first.pdf", "missing.pdf"])
    task.out_dir.mkdir()
    (task.out_dir / "first.pdf").write_bytes(make_pdf(1))
    queue._tasks[task.id] = task
    before = set(files.root.iterdir())
    try:
        assert client.post(f"/api/tasks/{task.id}/continue").status_code == 404
        assert set(files.root.iterdir()) == before
    finally:
        queue.delete(task.id)


def test_active_uploads_are_forced_to_download():
    result = client.post("/api/files/upload", files={"file": ("preview.html", b"<script>alert(1)</script>", "text/html")})
    assert result.status_code == 200
    preview = client.get(f"/api/files/{result.json()['id']}/view")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/octet-stream"
    assert preview.headers["content-disposition"].startswith("attachment")
    assert preview.headers["x-content-type-options"] == "nosniff"
