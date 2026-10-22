import base64
import io
import json

import pypdf
from reportlab.pdfgen import canvas

from conftest import make_pdf, make_png, open_out, run_tool, store


def _texts(data):
    return [p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages]


def test_edit_draws_everything(pdf3):
    png = "data:image/png;base64," + base64.b64encode(make_png(50, 50)).decode()
    task, out = run_tool(
        "edit", [pdf3],
        appendTextOperations=[json.dumps({"text": "Hello editor\nsecond line", "font": "Helvetica", "fontSize": "14.00",
                                          "position": {"x": 72, "y": 500}, "color": "#112233", "pages": "2"})],
        editTextOperations=[{"page": "1", "area": {"x": 70, "y": 760, "width": 120, "height": 30}, "text": "Replaced",
                             "fontSize": 20, "position": {"x": 72, "y": 768}}],
        shapeOperations=[{"pages": "1", "position": {"x": 300, "y": 300}, "width": 100, "height": 50, "shape": "ellipse",
                          "borderWidth": 2, "borderColor": "#ff0000", "backgroundColor": "#00ff00"}],
        imageOperations=[{"pages": "1-", "position": {"x": 400, "y": 600}, "width": 50, "height": 50, "image": png, "exceptPages": [3]}],
        highlightTextOperations=[{"page": "1", "boundingBoxes": [{"left": 70, "right": 300, "top": 740, "bottom": 725}], "kind": "highlight"}],
        appendDraw=[{"page": "1", "inklist": [[100, 100, 120, 130, 140, 100]], "color": "#0000ff", "lineSize": 3}],
        appendLine=[{"page": "3", "points": [50, 50, 200, 200], "kind": "arrow"}],
        appendLinkOperations=[{"page": "1", "boundingBoxes": [{"left": 10, "right": 100, "top": 100, "bottom": 80}], "href": "example.com"},
                              {"page": "1", "boundingBoxes": [{"left": 10, "right": 100, "top": 60, "bottom": 40}], "href": "3", "kind": "page"}],
    )
    texts = _texts(out["three.pdf"])
    assert "Hello editor" in texts[1] and "second line" in texts[1]
    assert "Replaced" in texts[0]
    pdf = open_out(out["three.pdf"])
    links = [a for a in pdf.pages[0].obj.Annots if a.Subtype == "/Link"]
    assert len(links) == 2 and str(links[0].A.URI) == "https://example.com"


def test_page_order_insert_delete_rotate(pdf3):
    task, out = run_tool("edit", [pdf3], pageOrder=["3:0", "-1:0", "1:90"],
                         appendTextOperations=[{"text": "on blank", "position": {"x": 50, "y": 50}, "pages": "2"}])
    pdf = open_out(out["three.pdf"])
    assert len(pdf.pages) == 3
    assert int(pdf.pages[2].obj.get("/Rotate", 0)) == 90
    texts = _texts(out["three.pdf"])
    assert texts[0].startswith("Page 3") and "on blank" in texts[1]


def test_create_and_fill_form_fields(pdf3):
    task, out = run_tool("editForms", [pdf3], appendFormFieldOperations=[
        {"page": "1", "kind": "text", "name": "full name", "boundingBox": {"left": 72, "bottom": 600, "right": 300, "top": 620}},
        {"page": "1", "kind": "checkbox", "name": "agree", "boundingBox": {"left": 72, "bottom": 560, "right": 86, "top": 574}},
    ])
    form = store(out["three.pdf"], "form.pdf")
    fields = pypdf.PdfReader(form.path).get_fields()
    assert set(fields) == {"full_name", "agree"}
    task, out = run_tool("fillSign", [form], formValues={"full_name": "Ada Lovelace", "agree": True})
    fields = pypdf.PdfReader(io.BytesIO(out["form.pdf"])).get_fields()
    assert fields["full_name"]["/V"] == "Ada Lovelace"
    assert fields["agree"]["/V"] == "/Yes"


def test_legacy_page_ops(pdf3):
    _, out = run_tool("edit", [pdf3], deletePageOperations=[{"page": "2"}], insertPageOperations=[{"page": "1"}],
                      rotatePageOperations=[{"pages": "3", "degrees": 180}])
    pdf = open_out(out["three.pdf"])
    assert len(pdf.pages) == 3 and int(pdf.pages[2].obj.get("/Rotate", 0)) == 180
