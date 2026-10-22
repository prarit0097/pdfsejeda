"""Cross-tool rejection, missing-resource and file-serving contracts."""
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.tools.registry import all_tools
from conftest import make_pdf


client=TestClient(app)
TOOLS=all_tools()


@pytest.mark.parametrize("tool", [t for t in TOOLS if t.type != "htmlToPdf"], ids=lambda t:t.type)
def test_every_file_tool_rejects_empty_submission(tool):
    r=client.post("/api/tasks",json={"type":tool.type,"files":[]})
    assert r.status_code==400 and "file" in r.text.lower()


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t:t.type)
def test_every_tool_rejects_unsupported_input_type(tool):
    r=client.post("/api/files/upload",files={"file":("unsupported.pool",b"not a document","application/octet-stream")})
    assert r.status_code==200
    ids=[r.json()["id"]]*max(1,tool.min_files)
    response=client.post("/api/tasks",json={"type":tool.type,"files":ids})
    assert response.status_code==400 and "supported file type" in response.text


@pytest.mark.parametrize("method,path", [
    ("get","/api/files/missing"),("get","/api/files/missing/view"),
    ("get","/api/files/missing/outline"),("get","/api/files/missing/metadata"),
    ("post","/api/files/missing/touch"),("post","/api/files/missing/password"),
    ("get","/api/tasks/missing/change"),("post","/api/tasks/missing/cancel"),
    ("post","/api/tasks/missing/continue"),("get","/api/tasks/missing/download/file.pdf"),
])
def test_missing_resource_endpoints(method,path):
    r=getattr(client,method)(path,json={} if method=="post" else None) if method=="post" else client.get(path)
    assert r.status_code==404
    assert "traceback" not in r.text.lower()


@pytest.mark.parametrize("body", [[],None,"text",{"type":"extractPages","files":[17]}, {"type":"extractPages","files":{"id":"abc"}}])
def test_task_rejects_wrong_body_or_file_list_shape(body):
    r=client.post("/api/tasks",json=body)
    assert r.status_code==400


def test_view_supports_pdf_range_requests_and_invalid_ranges():
    data=make_pdf(2)
    info=client.post("/api/files/upload",files={"file":("range.pdf",data,"application/pdf")}).json()
    url=f"/api/files/{info['id']}/view"
    r=client.get(url,headers={"Range":"bytes=0-15"})
    assert r.status_code==206 and r.content==data[:16]
    assert r.headers["content-range"]==f"bytes 0-15/{len(data)}"
    assert client.get(url,headers={"Range":f"bytes={len(data)+10}-"}).status_code==416
    assert client.get(url,headers={"Range":"bytes=-10"}).content==data[-10:]


@pytest.mark.parametrize("filename,mime", [("attack.svg","image/svg+xml"),("attack.js","text/javascript"),("attack.html","text/html")])
def test_active_uploaded_files_cannot_execute_inline(filename,mime):
    info=client.post("/api/files/upload",files={"file":(filename,b"<script>bad()</script>",mime)}).json()
    r=client.get(f"/api/files/{info['id']}/view")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"]=="application/octet-stream"
    assert r.headers["x-content-type-options"]=="nosniff"


def test_corrupt_pdf_is_reported_without_server_error():
    r=client.post("/api/files/upload",files={"file":("broken.pdf",b"%PDF-1.4 invalid","application/pdf")})
    assert r.status_code==200 and r.json().get("damaged")
    fid=r.json()["id"]
    assert client.get(f"/api/files/{fid}/metadata").status_code==400
    assert client.get(f"/api/files/{fid}/outline").status_code==400
    assert client.post(f"/api/files/{fid}/password",json={"password":"x"}).status_code==400


def test_chunk_rejects_inconsistent_upload_range_and_missing_headers():
    for value in ("nonsense","bytes 9-2/10","bytes 0-10/5"):
        r=client.post("/api/files/upload-chunked",files={"file":("a.pdf",b"a")},headers={"X-Upload-Id":uuid.uuid4().hex,"Content-Range":value})
        assert r.status_code==400
    assert client.post("/api/files/upload-chunked",files={"file":("a.pdf",b"a")}).status_code==422
