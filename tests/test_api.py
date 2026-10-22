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
