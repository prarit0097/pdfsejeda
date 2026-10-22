from fastapi.testclient import TestClient

from app.main import app
from app.jobs import queue
from conftest import make_pdf, store


def test_result_entry_point_and_expiry():
    client = TestClient(app)
    task = queue.submit("extractPages", [store(make_pdf(1)).id], {"pages": "1"})
    response = client.get("/result", params={"id": task.id}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/extract-pdf-pages#results-{task.id}"
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/result?id=unknown").status_code == 404


def test_developer_guides_and_self_hosted_pdf_loader():
    client = TestClient(app)
    for slug in ("developers", "html-pdf-api"):
        response = client.get("/" + slug)
        assert response.status_code == 200
        assert "/api/tasks" in response.text and "Keep IDs private" in response.text
    page = client.get("/pdf-editor")
    assert "/static/js/pdf-loader.js" in page.text and "cdnjs.cloudflare.com" not in page.text
    assert "wasm-unsafe-eval" in page.headers["content-security-policy"]
    assert client.get("/static/vendor/pdfjs/pdf.min.mjs").status_code == 200
