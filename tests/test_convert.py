import io
import zipfile

import pytest
from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.tools.convert import tesseract_path
from conftest import make_pdf, make_png, open_out, run_tool, store


def _table_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 780, "Quarterly report")
    c.setFont("Helvetica", 11)
    c.drawString(72, 750, "Revenue grew in every region during the quarter.")
    rows = [["Region", "Q1", "Q2"], ["North", "1200", "1350"], ["South", "980", "1010"]]
    x0, y0, cw, rh = 72, 700, 120, 22
    for r, row in enumerate(rows):
        for col, v in enumerate(row):
            c.rect(x0 + col * cw, y0 - r * rh, cw, rh)
            c.drawString(x0 + col * cw + 6, y0 - r * rh + 7, v)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_to_images(pdf3):
    task, out = run_tool("pdfToImage", [pdf3], imageFormat="png", resolution=75, pages="1-2")
    assert sorted(n for n in out if n.endswith(".png")) == ["three-1.png", "three-2.png"]
    task, out = run_tool("pdfToImage", [pdf3], imageFormat="tiff", tiffSingleFileWithAllPages=True, imageColorType="black_white")
    assert task.result_filename == "three.tif"


def test_images_to_pdf():
    a = store(make_png(400, 200), "a.png", "image/png")
    b = store(make_png(100, 300), "b.png", "image/png")
    task, out = run_tool("jpgToPdf", [a, b], pageSize="a4", pageMargin="small", rotations=[90, 0])
    pdf = open_out(out[task.result_filename])
    assert len(pdf.pages) == 2


def test_extract_images_and_text():
    from test_modify import _image_pdf

    f = store(_image_pdf(), "pics.pdf")
    task, out = run_tool("extractImages", [f])
    assert task.remark == "Extracted 1 image"
    t = store(make_pdf(2), "t.pdf")
    _, out = run_tool("extractText", [t])
    assert "Page 2" in out["t.txt"].decode()


def test_pdf_to_excel_and_csv():
    f = store(_table_pdf(), "report.pdf")
    _, out = run_tool("pdfToExcelNext", [f])
    ws = load_workbook(io.BytesIO(out["report.xlsx"])).active
    values = [[c.value for c in row] for row in ws.iter_rows()]
    assert ["North", 1200, 1350] in values
    _, out = run_tool("pdfToExcelNext", [f], exportFormat="csv")
    assert "South,980,1010" in out["report.csv"].decode("utf-8-sig")


def test_pdf_to_word():
    from docx import Document

    f = store(_table_pdf(), "report.pdf")
    _, out = run_tool("pdfToOfficeWord", [f])
    d = Document(io.BytesIO(out["report.docx"]))
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Quarterly report" in text and "Revenue grew" in text
    assert d.tables and d.tables[0].cell(1, 0).text == "North"


def test_pdf_to_ppt(pdf3):
    from pptx import Presentation

    _, out = run_tool("pdfToPpt", [pdf3])
    prs = Presentation(io.BytesIO(out["three.pptx"]))
    assert len(prs.slides) == 3


def test_word_to_pdf_fallback(monkeypatch):
    from docx import Document

    monkeypatch.setattr("app.tools.convert.soffice_path", lambda: None)

    d = Document()
    d.add_heading("Hello", 1)
    d.add_paragraph("Body text")
    buf = io.BytesIO()
    d.save(buf)
    f = store(buf.getvalue(), "letter.docx", "application/octet-stream")
    task, out = run_tool("docToPdf", [f])
    import pypdf

    assert "Body text" in pypdf.PdfReader(io.BytesIO(out["letter.pdf"])).pages[0].extract_text()


@pytest.mark.skipif(not tesseract_path(), reason="Tesseract not installed")
def test_ocr(pdf3):
    from app.storage import files

    _, out = run_tool("pdfToImage", [pdf3], imageFormat="png", pages="1", resolution=150)
    img = store(out["three-1.png"], "scan.png", "image/png")
    _, out = run_tool("jpgToPdf", [img])
    scan = store(out["scan.pdf"], "scan.pdf")
    _, out = run_tool("ocr", [scan], lang="eng")
    import pypdf

    assert "Page" in pypdf.PdfReader(io.BytesIO(out["scan.pdf"])).pages[0].extract_text()


def test_word_engine_failure_falls_back(monkeypatch):
    import subprocess
    from docx import Document

    monkeypatch.setattr("app.tools.convert.soffice_path", lambda: "soffice")
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "soffice")
    monkeypatch.setattr("app.tools.convert._run", fail)
    d = Document()
    d.add_paragraph("Recovered body")
    buf = io.BytesIO()
    d.save(buf)
    task, out = run_tool("docToPdf", [store(buf.getvalue(), "recovered.docx")])
    import pypdf
    assert "Recovered body" in pypdf.PdfReader(io.BytesIO(out["recovered.pdf"])).pages[0].extract_text()
    assert any("LibreOffice failed" in warning for warning in task.warnings)


def test_word_to_pdf_real_engine():
    from app.tools.convert import soffice_path
    from docx import Document
    import pypdf

    if not soffice_path():
        pytest.skip("LibreOffice not installed")
    d = Document()
    d.add_paragraph("Real engine conversion")
    buf = io.BytesIO()
    d.save(buf)
    task, out = run_tool("docToPdf", [store(buf.getvalue(), "engine.docx")])
    assert not task.warnings, "Installed LibreOffice failed; fallback must not mask an engine regression"
    assert "Real engine conversion" in pypdf.PdfReader(io.BytesIO(out["engine.pdf"])).pages[0].extract_text()


def test_html_resource_pins_every_redirect(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.tools.convert import _fetch_html_resource

    monkeypatch.setattr("app.tools.convert.resolve_public", lambda url: ["93.184.216.34"])
    def fetch(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.org"
        assert request.extensions["sni_hostname"] == "example.org"
        if request.url.path == "/page":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, content=b"final page")
    request = SimpleNamespace(url="https://example.org/page", method="GET", headers={}, post_data_buffer=None)
    status, headers, body = _fetch_html_resource(request, transport=httpx.MockTransport(fetch))
    assert status == 200 and body == b"final page"
    assert headers["x-pdfnova-final-url"] == "https://example.org/final"


def test_html_resource_rejects_private_redirect(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.security import UnsafeUrl
    from app.tools.convert import _fetch_html_resource
    seen = []
    def resolve(url):
        seen.append(url)
        if "127.0.0.1" in url:
            raise UnsafeUrl("private redirect")
        return ["93.184.216.34"]
    monkeypatch.setattr("app.tools.convert.resolve_public", resolve)
    request = SimpleNamespace(url="https://example.org/page", method="GET", headers={}, post_data_buffer=None)
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={"Location":"http://127.0.0.1/private"}))
    with pytest.raises(UnsafeUrl, match="private redirect"):
        _fetch_html_resource(request, transport=transport)
    assert seen == [request.url, "http://127.0.0.1/private"]


def test_html_redirect_preserves_relative_assets(monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import httpx
    import pypdf
    from app.tools import convert
    from types import SimpleNamespace

    calls = []
    resources = {
        "/start": (302, {"location":"/folder/index.html"}, b""),
        "/folder/index.html": (200, {"content-type":"text/html"}, b'<link rel="stylesheet" href="style.css"><h1>Redirect target</h1><img src="image.png"><script>document.write(location.pathname)</script>'),
        "/folder/style.css": (302, {"location":"/styles/final.css"}, b""),
        "/styles/final.css": (200, {"content-type":"text/css"}, b'h1::after{content:" CSS LOADED"}body{background-image:url(bg.png)}'),
        "/folder/image.png": (200, {"content-type":"image/png"}, make_png()),
        "/styles/bg.png": (200, {"content-type":"image/png"}, make_png()),
    }
    def fetch(request):
        calls.append(request.url.path)
        status, headers, body = resources[request.url.path]
        return httpx.Response(status, headers=headers, content=body)
    original = convert._fetch_html_resource
    monkeypatch.setattr(convert, "resolve_public", lambda url: ["93.184.216.34"])
    monkeypatch.setattr(convert, "_check_host", lambda url: None)
    monkeypatch.setattr(convert, "_scroll_through", lambda page: None)
    transport = httpx.MockTransport(fetch)
    monkeypatch.setattr(convert, "_fetch_html_resource", lambda request: original(request, transport=transport))
    _, out = run_tool("htmlToPdf", [], urls="https://fixture.example/start", partialContentAllowed=False)
    pdf = pypdf.PdfReader(io.BytesIO(next(iter(out.values()))))
    assert "CSS LOADED" in pdf.pages[0].extract_text()
    assert "/folder/index.html" in pdf.pages[0].extract_text()
    assert len(pdf.pages[0].images) >= 1
    assert set(resources).issubset(set(calls))


def test_html_resource_blocks_private_and_large_responses(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app.security import UnsafeUrl
    from app.tools.convert import _fetch_html_resource

    request = SimpleNamespace(url="http://127.0.0.1/private", method="GET", headers={}, post_data_buffer=None)
    with pytest.raises(UnsafeUrl):
        _fetch_html_resource(request)
    monkeypatch.setattr("app.tools.convert.resolve_public", lambda url: ["93.184.216.34"])
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"12345"))
    with pytest.raises(UnsafeUrl, match="too large"):
        _fetch_html_resource(request, transport=transport, max_bytes=4)


def test_html_to_pdf_browser_blocks_private_subresources(monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    import pypdf

    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error:
            pytest.skip("Chromium not installed")
        browser.close()
    monkeypatch.setattr("app.tools.convert._scroll_through", lambda page: None)
    from app.tools import convert
    fetch_resource = convert._fetch_html_resource
    seen = []
    def checked_fetch(request):
        seen.append(request.url)
        assert "doubleclick.net" not in request.url, "Ad requests must be blocked before fetching"
        return fetch_resource(request)
    monkeypatch.setattr(convert, "_fetch_html_resource", checked_fetch)
    html = '''<h1>Safe HTML conversion</h1><div id="cookie-banner">UNWANTED COOKIE NOTICE</div>
        <img src="https://ad.doubleclick.net/ad.png">
        <img src="http://127.0.0.1:1/private"><script>
        document.write(navigator.language + ' ' + Intl.DateTimeFormat().resolvedOptions().timeZone);
        new WebSocket("ws://127.0.0.1:1/private");</script>'''
    task, out = run_tool("htmlToPdf", [], htmlCode=html, lang="en_GB", timezone="America/New_York",
                         includeHeaderFooterDetails=True, hideNotices=True, blockAds=True)
    text = pypdf.PdfReader(io.BytesIO(out["page-1.pdf"])).pages[0].extract_text()
    assert "Safe HTML conversion" in text and "en-GB" in text and "America/New_York" in text
    assert "UNWANTED COOKIE NOTICE" not in text
    assert any("resources" in warning for warning in task.warnings)
    assert "http://127.0.0.1:1/private" in seen
    from app.jobs import TaskError
    with pytest.raises(TaskError, match="resources could not be loaded"):
        run_tool("htmlToPdf", [], htmlCode=html, partialContentAllowed=False, blockAds=True)


def test_html_rejects_invalid_locale():
    pytest.importorskip("playwright.sync_api")
    from app.jobs import TaskError
    with pytest.raises(TaskError, match="valid browser language"):
        run_tool("htmlToPdf", [], htmlCode="<h1>test</h1>", lang="../../invalid")
