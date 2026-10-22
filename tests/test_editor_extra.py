"""Edge cases for the PDF editor save (task types edit / fillSign / editForms)."""
import base64
import io
import json

import pikepdf
import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.jobs import TaskError
from app.storage import files
from app.tools.draw import user_to_visible
from conftest import make_pdf, open_out, run_tool, store


def _texts(data):
    return [p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages]


def _png(mode, size=(40, 20), color=None):
    from PIL import Image

    buf = io.BytesIO()
    img = Image.new(mode, size, color if color is not None else 0)
    if mode == "P":
        img.info["transparency"] = 0
    # PNG cannot encode CMYK. JPEG exercises the editor's actual CMYK path.
    fmt, mime = ("JPEG", "image/jpeg") if mode == "CMYK" else ("PNG", "image/png")
    img.save(buf, fmt)
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _img_op(src, page="1"):
    return {"pages": page, "position": {"x": 100, "y": 100}, "width": 80, "height": 40, "image": src}


def _form_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    f = c.acroForm
    f.textfield(name="name", x=140, y=770, width=200, height=20)
    f.checkbox(name="agree", x=140, y=735, size=16)
    f.radio(name="color", value="red", selected=False, x=140, y=695, size=16)
    f.radio(name="color", value="Yes", selected=False, x=180, y=695, size=16)
    f.choice(name="fruit", options=["Apple", "Banana", "Cherry"], value="Apple", x=140, y=650, width=120, height=20)
    c.showPage()
    c.save()
    return buf.getvalue()


def _rotated_pdf(rotate=90, crop=(30, 40, 565, 800)):
    pdf = pikepdf.open(io.BytesIO(make_pdf(2)))
    pdf.pages[0].obj.Rotate = rotate
    pdf.pages[0].obj.CropBox = list(crop)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def _visible_rect(page, rect):
    m = user_to_visible(page)
    pts = [(m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]) for x, y in ((rect[0], rect[1]), (rect[2], rect[3]))]
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    return [round(xs[0], 2), round(ys[0], 2), round(xs[1], 2), round(ys[1], 2)]


# ---------------------------------------------------------------- page order


@pytest.mark.parametrize("order", ['["2:0", "1:0"]', "2:0,1:0", ["2:0", "1:0"]])
def test_page_order_accepts_json_string_and_csv(pdf3, order):
    _, out = run_tool("edit", [pdf3], pageOrder=order)
    texts = _texts(out["three.pdf"])
    assert len(texts) == 2 and texts[0].startswith("Page 2") and texts[1].startswith("Page 1")


@pytest.mark.parametrize("entry", ["1:45", "x:0", "1:0:abc", "1:0:5x5:9", "-1:0:0x100"])
def test_page_order_rejects_bad_entries(pdf3, entry):
    with pytest.raises(TaskError):
        run_tool("edit", [pdf3], pageOrder=[entry])


def test_page_order_out_of_range(pdf3):
    with pytest.raises(TaskError, match="does not exist"):
        run_tool("edit", [pdf3], pageOrder=["1:0", "9:0"])


def test_blank_page_takes_size_from_page_order(pdf3):
    # the browser sends the blank page size it showed, so objects land where they were drawn
    _, out = run_tool("edit", [pdf3], pageOrder=["1:90", "-1:90:300x500"],
                      shapeOperations=[{"pages": "2", "position": {"x": 10, "y": 10}, "width": 50, "height": 50}])
    pdf = open_out(out["three.pdf"])
    blank = pdf.pages[1]
    assert [float(v) for v in blank.mediabox] == [0, 0, 300, 500]
    assert int(blank.obj.Rotate) == 90


def test_blank_page_without_size_copies_previous(pdf_landscape):
    _, out = run_tool("edit", [pdf_landscape], pageOrder=["1:0", "-1:0"])
    pdf = open_out(out["wide.pdf"])
    assert [round(float(v)) for v in pdf.pages[1].mediabox] == [0, 0, 842, 595]


def test_duplicate_pages_are_stamped_independently(pdf3):
    _, out = run_tool("edit", [pdf3], pageOrder=["1:0", "1:0", "1:90"],
                      appendTextOperations=[{"text": "only-first", "position": {"x": 72, "y": 400}, "pages": "1"},
                                            {"text": "only-second", "position": {"x": 72, "y": 400}, "pages": "2"}])
    texts = _texts(out["three.pdf"])
    assert len(texts) == 3
    assert "only-first" in texts[0] and "only-second" not in texts[0]
    assert "only-second" in texts[1] and "only-first" not in texts[1]
    assert "only" not in texts[2]
    pdf = open_out(out["three.pdf"])
    assert int(pdf.pages[2].obj.Rotate) == 90


# ---------------------------------------------------------------- invalid input


def test_invalid_json_operation_is_a_clear_error(pdf3):
    with pytest.raises(TaskError, match="Invalid editor data"):
        run_tool("edit", [pdf3], appendTextOperations=["{not json"])


def test_invalid_form_values_is_a_clear_error(pdf3):
    with pytest.raises(TaskError, match="Invalid form values"):
        run_tool("fillSign", [pdf3], formValues="{oops")


def test_out_of_range_pages_are_ignored(pdf3):
    _, out = run_tool("edit", [pdf3],
                      appendTextOperations=[{"text": "nowhere", "position": {"x": 72, "y": 400}, "pages": "9"},
                                            {"text": "here", "position": {"x": 72, "y": 400}, "pages": "3"}],
                      appendLinkOperations=[{"page": "7", "href": "x.com", "boundingBoxes": [{"left": 0, "right": 9, "top": 9, "bottom": 0}]},
                                            {"page": "1", "href": "12", "kind": "page", "boundingBoxes": [{"left": 0, "right": 9, "top": 9, "bottom": 0}]}],
                      appendFormFieldOperations=[{"page": "5", "kind": "text", "boundingBox": {"left": 0, "right": 9, "top": 9, "bottom": 0}}])
    texts = _texts(out["three.pdf"])
    assert "here" in texts[2] and not any("nowhere" in t for t in texts)
    pdf = open_out(out["three.pdf"])
    assert "/Annots" not in pdf.pages[0].obj


@pytest.mark.parametrize("src", ["data:image/png;base64,!!!notbase64", "data:image/png;base64," + base64.b64encode(b"hello").decode()])
def test_unreadable_image_is_a_clear_error(pdf3, src):
    with pytest.raises(TaskError, match="image"):
        run_tool("edit", [pdf3], imageOperations=[_img_op(src)])


def test_expired_image_file_id(pdf3):
    with pytest.raises(TaskError, match="expired"):
        run_tool("edit", [pdf3], imageOperations=[_img_op("does-not-exist")])


# ---------------------------------------------------------------- images


@pytest.mark.parametrize("mode,color", [("RGBA", (255, 0, 0, 128)), ("LA", (0, 0)), ("P", None), ("CMYK", (0, 0, 0, 0)), ("1", 1)])
def test_image_modes(pdf3, mode, color):
    _, out = run_tool("edit", [pdf3], imageOperations=[_img_op(_png(mode, color=color))])
    pdf = open_out(out["three.pdf"])
    assert len(pdf.pages) == 3
    if mode in ("RGBA", "LA", "P"):  # transparency kept as a soft mask
        found = []

        def walk(res):
            for _, x in (res.get("/XObject") or {}).items():
                if x.get("/Subtype") == "/Image":
                    found.append("/SMask" in x or "/Mask" in x)
                elif "/Resources" in x:
                    walk(x.Resources)
        walk(pdf.pages[0].obj.Resources)
        assert found and all(found)


def test_image_by_file_id(pdf3):
    img = files.save_bytes("pic.png", base64.b64decode(_png("RGB", color=(0, 128, 0)).split(",")[1]), "image/png")
    _, out = run_tool("edit", [pdf3], imageOperations=[_img_op(img.id)])
    assert len(open_out(out["three.pdf"]).pages) == 3


# ---------------------------------------------------------------- text


def test_unicode_and_control_characters(pdf3):
    _, out = run_tool("edit", [pdf3], appendTextOperations=[
        {"text": "नमस्ते दुनिया", "position": {"x": 72, "y": 400}, "pages": "1"},
        {"text": "a\r\nb\tc", "position": {"x": 72, "y": 300}, "pages": "1"}])
    text = _texts(out["three.pdf"])[0]
    assert "\r" not in text and "a" in text and "b" in text


def test_edit_text_whites_out_area(pdf3):
    _, out = run_tool("edit", [pdf3], editTextOperations=[
        {"page": "1", "area": {"x": 70, "y": 760, "width": 200, "height": 30}, "text": "",
         "position": {"x": 72, "y": 770}}])
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(out["three.pdf"])[0]
    img = page.render(scale=1).to_pil().convert("L")
    h = img.height
    # the area (PDF y 760..790) is white after the edit
    box = img.crop((72, h - 788, 268, h - 762))
    assert min(box.getdata()) > 250


# ---------------------------------------------------------------- forms


def test_fill_radio_dropdown_checkbox():
    form = store(_form_pdf(), "form.pdf")
    _, out = run_tool("fillSign", [form], formValues=json.dumps({"name": "Ada", "agree": True, "color": "red", "fruit": "Cherry"}))
    fields = pypdf.PdfReader(io.BytesIO(out["form.pdf"])).get_fields()
    assert fields["name"]["/V"] == "Ada"
    assert fields["agree"]["/V"] == "/Yes"
    assert fields["color"]["/V"] == "/red"
    assert fields["fruit"]["/V"] == "Cherry"
    states = {}
    for a in pypdf.PdfReader(io.BytesIO(out["form.pdf"])).pages[0]["/Annots"]:
        a = a.get_object()
        if a.get("/Parent") is not None and a["/Parent"].get_object().get("/T") == "color":
            states[next(k for k in a["/AP"]["/N"].keys() if k != "/Off")] = a["/AS"]
    # choosing "red" must not switch on the radio whose export value happens to be "Yes"
    assert states == {"/red": "/red", "/Yes": "/Off"}


def test_fill_radio_with_yes_export_value():
    form = store(_form_pdf(), "form.pdf")
    _, out = run_tool("fillSign", [form], formValues={"color": "Yes", "agree": False})
    fields = pypdf.PdfReader(io.BytesIO(out["form.pdf"])).get_fields()
    assert fields["color"]["/V"] == "/Yes"
    assert fields["agree"].get("/V") in (None, "/Off")


def test_form_fields_on_rotated_page_keep_position_and_turn_with_page():
    src = store(_rotated_pdf(), "rot.pdf")
    box = {"left": 100, "bottom": 300, "right": 260, "top": 320}
    _, out = run_tool("editForms", [src], appendFormFieldOperations=[
        {"page": "1", "kind": "text", "name": "t", "boundingBox": box, "value": "hi"},
        {"page": "1", "kind": "checkbox", "name": "c", "boundingBox": {"left": 300, "bottom": 300, "right": 314, "top": 314}, "value": True}],
        appendLinkOperations=[{"page": "1", "href": "2", "kind": "page", "boundingBoxes": [box]}])
    pdf = open_out(out["rot.pdf"])
    page = pdf.pages[0]
    annots = {str(a.get("/T", a.Subtype)): a for a in page.obj.Annots}
    assert _visible_rect(page, annots["t"].Rect) == [100, 300, 260, 320]
    assert _visible_rect(page, annots["/Link"].Rect) == [100, 300, 260, 320]
    assert int(annots["t"].MK.R) == 90
    ap = annots["t"].AP.N
    # appearance is built upright (160 x 20) and turned by its matrix to fit the rotated rect
    assert [float(v) for v in ap.BBox] == [0, 0, 160, 20]
    assert [int(v) for v in ap.Matrix] == [0, 1, -1, 0, 0, 0]
    assert str(annots["c"].AS) == "/Yes"


def test_new_fields_with_existing_form_and_flatten():
    form = store(_form_pdf(), "form.pdf")
    _, out = run_tool("editForms", [form], appendFormFieldOperations=[
        {"page": "1", "kind": "text", "name": "extra field", "boundingBox": {"left": 72, "bottom": 500, "right": 200, "top": 520}}])
    names = set(pypdf.PdfReader(io.BytesIO(out["form.pdf"])).get_fields())
    assert {"name", "agree", "color", "fruit", "extra_field"} <= names
    filled = store(out["form.pdf"], "form2.pdf")
    _, out = run_tool("fillSign", [filled], formValues={"extra_field": "Flat value"}, flattenForms=True)
    pdf = open_out(out["form2.pdf"])
    assert "/AcroForm" not in pdf.Root
    assert "Flat value" in _texts(out["form2.pdf"])[0]


def test_password_protected_input():
    buf = io.BytesIO()
    pikepdf.open(io.BytesIO(make_pdf(1))).save(buf, encryption=pikepdf.Encryption(owner="o", user="secret"))
    f = store(buf.getvalue(), "locked.pdf")
    with pytest.raises(TaskError, match="password"):
        run_tool("edit", [f], appendTextOperations=[{"text": "x", "position": {"x": 9, "y": 9}, "pages": "1"}])
    f = files.set_password(f.id, "secret")
    _, out = run_tool("edit", [f], appendTextOperations=[{"text": "unlocked", "position": {"x": 72, "y": 400}, "pages": "1"}])
    assert "unlocked" in _texts(out["locked.pdf"])[0]
