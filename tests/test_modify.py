import io

import pikepdf
import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from conftest import make_pdf, make_png, open_out, run_tool, store


def _text(data, page=0):
    return pypdf.PdfReader(io.BytesIO(data)).pages[page].extract_text()


def _image_pdf():
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    import numpy as np

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    noise = (np.random.default_rng(1).random((1200, 1200, 3)) * 255).astype("uint8")
    c.drawImage(ImageReader(Image.fromarray(noise)), 50, 200, 400, 400)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_compress_reduces_images():
    f = store(_image_pdf(), "img.pdf")
    task, out = run_tool("compress", [f], imageQuality=0.65, imageDpi=72)
    assert len(out["img.pdf"]) < f.size
    assert "smaller" in task.remark


def test_compress_never_grows():
    f = store(make_pdf(1), "tiny.pdf")
    task, out = run_tool("compress", [f])
    assert len(out["tiny.pdf"]) <= f.size


def test_compress_strict_fails_when_not_reduced():
    from app.jobs import TaskError

    # First obtain an optimized PDF, so the second run cannot save more bytes.
    _, out = run_tool("compress", [store(make_pdf(1), "tiny.pdf")])
    f = store(out["tiny.pdf"], "optimized.pdf")
    with pytest.raises(TaskError, match="already optimized"):
        run_tool("compress", [f], failIfOutputSizeNotReduced=True)


def test_crop_margins_and_auto(pdf3):
    _, out = run_tool("crop", [pdf3], cropMode="margins", unit="cm", marginTop=1, marginBottom=1, marginLeft=1, marginRight=1)
    pdf = open_out(out["three.pdf"])
    box = [float(v) for v in pdf.pages[0].obj.CropBox]
    assert abs((box[2] - box[0]) - (595.28 - 2 * 72 / 2.54)) < 1
    _, out = run_tool("crop", [pdf3], cropMode="auto")
    pdf = open_out(out["three.pdf"])
    box = [float(v) for v in pdf.pages[0].obj.CropBox]
    assert box[2] - box[0] < 520 and box[0] > 40  # content starts at x=60


def test_resize_to_letter(pdf3):
    _, out = run_tool("resizePages", [pdf3], pageSize="letter")
    pdf = open_out(out["three.pdf"])
    assert [round(float(v)) for v in pdf.pages[0].mediabox] == [0, 0, 612, 792]
    assert "Page 1" in _text(out["three.pdf"])


def test_nup(pdf3):
    _, out = run_tool("nup", [pdf3], n=2)
    pdf = open_out(out["three.pdf"])
    assert len(pdf.pages) == 2
    w, h = (float(v) for v in pdf.pages[0].mediabox[2:])
    assert w > h


def test_flip_and_grayscale(pdf3):
    _, out = run_tool("flip", [pdf3], flipMode="horizontal")
    assert len(open_out(out["three.pdf"]).pages) == 3
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFillColorRGB(1, 0, 0)
    c.rect(10, 10, 100, 100, fill=1)
    c.showPage()
    c.save()
    f = store(buf.getvalue(), "red.pdf")
    _, out = run_tool("grayscale", [f])
    pdf = open_out(out["red.pdf"])
    content = pdf.pages[0].obj.Contents.read_bytes()
    assert b" rg" not in content and b" g" in content


def test_deskew_detects_rotation():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.translate(300, 420)
    c.rotate(3)
    c.setFont("Helvetica", 14)
    for i in range(30):
        c.drawString(-250, 300 - i * 20, "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod")
    c.showPage()
    c.save()
    f = store(buf.getvalue(), "skew.pdf")
    import pypdfium2 as pdfium
    from app.tools.modify import estimate_skew

    doc = pdfium.PdfDocument(str(f.path))
    angle = estimate_skew(doc, 0)
    doc.close()
    assert -3.6 < angle < -2.4, angle
    task, out = run_tool("deskew", [f])
    assert "Straightened 1 page" in task.remark


def test_flatten_modes(pdf3):
    _, out = run_tool("flatten", [pdf3], flattenMode="all", resolution=75)
    pdf = open_out(out["three.pdf"])
    assert len(pdf.pages) == 3 and "/XObject" in pdf.pages[0].obj.Resources
    _, out = run_tool("flatten", [pdf3], flattenMode="onlyforms")
    assert len(open_out(out["three.pdf"]).pages) == 3


def test_repair(pdf3):
    data = pdf3.path.read_bytes()
    broken = data[: data.rfind(b"xref")]  # drop the xref table and trailer
    f = store(broken, "broken.pdf")
    task, out = run_tool("repair", [f])
    assert len(open_out(out["broken.pdf"]).pages) == 3


def test_page_numbers_and_header(pdf3):
    _, out = run_tool("pageNumbers", [pdf3], pattern="Page [PAGE_ARABIC] of [TOTAL_PAGES_ARABIC]", pageLocation="bottom-right")
    assert "Page 2 of 3" in _text(out["three.pdf"], 1)
    _, out = run_tool("headerFooter", [pdf3], pattern="[BASE_NAME] [PAGE_ROMAN]", pageLocation="top-left", addMargins=True)
    assert "three ii" in _text(out["three.pdf"], 1)


def test_bates_continues_across_files(pdf3):
    b = store(make_pdf(2), "b.pdf")
    task, out = run_tool("batesNumbering", [pdf3, b], style="number", batesStartFrom=7, batesDigits=4)
    assert "0011" in _text(out["b.pdf"], 1)


def test_watermark_text_and_image(pdf3):
    _, out = run_tool("watermark", [pdf3], watermarkText="DRAFT", opacity=30)
    assert "DRAFT" in _text(out["three.pdf"])
    img = store(make_png(), "logo.png", "image/png")
    _, out = run_tool("watermark", [pdf3, img], watermarkType="image", pageLocation="tile")
    assert list(out) == ["three.pdf"]


def test_encrypt_and_decrypt(pdf3):
    _, out = run_tool("encrypt", [pdf3], userPassword="s3cret")
    enc = store(out["three.pdf"], "locked.pdf")
    try:
        pikepdf.open(enc.path)
        raise AssertionError("should need a password")
    except pikepdf.PasswordError:
        pass
    from app.storage import files

    files.set_password(enc.id, "s3cret")
    enc = files.get(enc.id)
    _, out = run_tool("decrypt", [enc])
    assert not open_out(out["locked.pdf"]).is_encrypted


def test_metadata(pdf3):
    _, out = run_tool("editMetadata", [pdf3], **{"metadata.Title": "New title", "metadata.Author": "Me", "metadata.CreationDate": "2024-05-01 10:30"})
    pdf = open_out(out["three.pdf"])
    assert str(pdf.docinfo["/Title"]) == "New title" and str(pdf.docinfo["/CreationDate"]).startswith("D:20240501")
    _, out = run_tool("editMetadata", [pdf3], removeAllMetadata=True)
    assert "/Title" not in open_out(out["three.pdf"]).docinfo


def test_bookmarks(pdf3):
    _, out = run_tool("editBookmarks", [pdf3], bookmarks="Intro | 1\n  Detail | 2\nEnd | 3")
    pdf = open_out(out["three.pdf"])
    with pdf.open_outline() as o:
        assert [i.title for i in o.root] == ["Intro", "End"]
        assert o.root[0].children[0].title == "Detail"


def test_delete_annotations():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "link here")
    c.linkURL("https://example.com", (100, 690, 200, 710))
    c.showPage()
    c.save()
    f = store(buf.getvalue(), "ann.pdf")
    task, out = run_tool("deleteAnnotations", [f], annotationTypes="all")
    assert task.remark.startswith("Removed 1")


def test_rename_by_text():
    f = store(make_pdf(1, texts=["INV-2041"]), "scan001.pdf")
    _, out = run_tool("renameByText", [f], renamePattern="Invoice [TEXT]", area={"x": 60, "y": 40, "width": 300, "height": 50})
    assert "Invoice INV-2041.pdf" in out
