"""Advanced AcroForm creation, appearances, grouping and fill roundtrips."""
import io

import pikepdf
import pypdf
import pytest

from app.jobs import TaskError
from conftest import make_pdf, run_tool, store


def field(kind, name, **extra):
    return {"kind": kind, "name": name, "page": 1,
            "boundingBox": {"left": 60, "bottom": 100, "right": 260, "top": 160}, **extra}


def result_form(pdf3, operations, **extra):
    _, outputs = run_tool("editForms", [pdf3], appendFormFieldOperations=operations, **extra)
    return next(iter(outputs.values()))


def test_choice_fields_keep_export_values_labels_defaults_and_appearances(pdf3):
    data = result_form(pdf3, [
        field("dropdown", "country", options=[{"value": "in", "label": "India"}, {"value": "gb", "label": "United Kingdom"}], value="in", defaultValue="gb", required=True),
        field("listbox", "colors", options=["red", "green", "blue"], multiSelect=True, value=["blue", "red"]),
    ])
    reader = pypdf.PdfReader(io.BytesIO(data))
    fields = reader.get_fields()
    assert fields["country"]["/FT"] == "/Ch"
    assert fields["country"]["/Ff"] & 131072
    assert fields["country"]["/Ff"] & 2
    assert fields["country"]["/V"] == "in"
    assert fields["country"]["/DV"] == "gb"
    assert fields["country"]["/Opt"] == [["in", "India"], ["gb", "United Kingdom"]]
    assert fields["colors"]["/Ff"] & 2097152
    assert fields["colors"]["/V"] == ["red", "blue"]
    annots = [a.get_object() for a in reader.pages[0]["/Annots"]]
    assert b"India" in annots[0]["/AP"]["/N"].get_data()
    assert annots[1]["/I"] == [0, 2]


def test_choice_fields_fill_roundtrip_keeps_multiselect_as_array(pdf3):
    data = result_form(pdf3, [field("dropdown", "country", options=["India", "UK"], value="India"),
                             field("listbox", "colors", options=["red", "green", "blue"], multiSelect=True)])
    saved = store(data, "choices.pdf")
    _, outputs = run_tool("fillSign", [saved], formValues={"country": "UK", "colors": ["green", "blue"]})
    fields = pypdf.PdfReader(io.BytesIO(next(iter(outputs.values())))).get_fields()
    assert fields["country"]["/V"] == "UK"
    assert fields["colors"]["/V"] == ["green", "blue"]


def test_radio_group_across_pages_creates_one_parent_and_fills(pdf3):
    data = result_form(pdf3, [field("radio", "delivery", exportValue="post", value=True, required=True),
                             field("radio", "delivery", page=2, exportValue="email")])
    reader = pypdf.PdfReader(io.BytesIO(data))
    group = reader.get_fields()["delivery"]
    assert group["/Ff"] & 32768
    assert group["/Ff"] & 2
    assert group["/V"] == "/post" and group["/DV"] == "/post"
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.Root.AcroForm.Fields) == 1
        assert len(pdf.Root.AcroForm.Fields[0].Kids) == 2
        assert pdf.pages[0].obj.Annots[0].AS == "/post"
        assert pdf.pages[1].obj.Annots[0].AS == "/Off"
    saved = store(data, "radio.pdf")
    _, outputs = run_tool("fillSign", [saved], formValues={"delivery": "email"})
    filled = next(iter(outputs.values()))
    with pikepdf.open(io.BytesIO(filled)) as pdf:
        assert pdf.Root.AcroForm.Fields[0].V == "/email"
        assert pdf.pages[0].obj.Annots[0].AS == "/Off"
        assert pdf.pages[1].obj.Annots[0].AS == "/email"


def test_radio_group_can_extend_existing_form(pdf3):
    first = result_form(pdf3, [field("radio", "group", exportValue="A")])
    saved = store(first, "extend.pdf")
    data = result_form(saved, [field("radio", "group", exportValue="B", value=True)])
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.Root.AcroForm.Fields) == 1
        assert len(pdf.Root.AcroForm.Fields[0].Kids) == 2
        assert pdf.Root.AcroForm.Fields[0].V == "/B"


def test_text_comb_has_maximum_default_and_separate_character_positions(pdf3):
    data = result_form(pdf3, [field("text", "code", value="ABCDE", defaultValue="XYZ", maxLength=4, comb=True)])
    reader = pypdf.PdfReader(io.BytesIO(data))
    f = reader.get_fields()["code"]
    assert f["/Ff"] & 16777216
    assert f["/V"] == "ABCD" and f["/DV"] == "XYZ"
    annot = reader.pages[0]["/Annots"][0].get_object()
    assert annot["/MaxLen"] == 4
    assert annot["/AP"]["/N"].get_data().count(b" Tj ET") == 4


@pytest.mark.parametrize("kind", ["dropdown", "listbox", "radio", "text"])
def test_advanced_fields_on_rotated_pages_have_upright_appearance(pdf3, kind):
    kwargs = {"options": ["A", "B"], "value": "A"} if kind in ("dropdown", "listbox") else {"value": True} if kind == "radio" else {"value": "hello"}
    data = result_form(pdf3, [field(kind, "rotated", **kwargs)], pageOrder=["1:90"])
    with pikepdf.open(io.BytesIO(data)) as pdf:
        widget = pdf.pages[0].obj.Annots[0]
        assert widget.MK.R == 90
        stream = widget.AP.N.Yes if kind == "radio" else widget.AP.N
        assert list(stream.BBox) == [0, 0, 200, 60]
        assert "/Matrix" in stream
        assert all(float(x) == float(x) for x in widget.Rect)


@pytest.mark.parametrize("operation, message", [
    (field("dropdown", "x", options=[]), "options"),
    (field("listbox", "x", options=["same", "same"]), "unique"),
    (field("dropdown", "x", options=["valid"], value="invalid"), "option"),
    (field("text", "x", comb=True), "maximum length"),
    (field("text", "x", comb=True, maxLength=3, multiline=True), "multiline"),
    (field("radio", "x", exportValue="Off"), "Off"),
    (field("unknown", "x"), "Unsupported"),
])
def test_invalid_field_data_is_rejected(pdf3, operation, message):
    with pytest.raises(TaskError, match=message):
        result_form(pdf3, [operation])


def test_duplicate_names_and_radio_values_are_rejected(pdf3):
    with pytest.raises(TaskError, match="names"):
        result_form(pdf3, [field("text", "same"), field("dropdown", "same", options=["A"])])
    with pytest.raises(TaskError, match="export values"):
        result_form(pdf3, [field("radio", "same", exportValue="A"), field("radio", "same", exportValue="A")])


def test_choice_fill_renders_labels_and_preserves_one_multiselect_value(pdf3):
    choices = [{"value": "a", "label": "Alpha"}, {"value": "b", "label": "Beta"}]
    data = result_form(pdf3, [field("dropdown", "single", options=choices),
                             field("listbox", "multi", options=choices, multiSelect=True)])
    saved = store(data, "labels.pdf")
    _, outputs = run_tool("fillSign", [saved], formValues={"single": "b", "multi": ["a"]})
    reader = pypdf.PdfReader(io.BytesIO(next(iter(outputs.values()))))
    fields = reader.get_fields()
    assert fields["single"]["/V"] == "b"
    assert fields["multi"]["/V"] == ["a"]
    widgets = [a.get_object() for a in reader.pages[0]["/Annots"]]
    assert b"Beta" in widgets[0]["/AP"]["/N"].get_data()
    assert b"Alpha" in widgets[1]["/AP"]["/N"].get_data()
    assert widgets[1]["/I"] == [0]


def test_radio_deselection_clears_parent_value(pdf3):
    data = result_form(pdf3, [field("radio", "group", exportValue="A", value=True),
                             field("radio", "group", exportValue="B")])
    saved = store(data, "clear-radio.pdf")
    _, outputs = run_tool("fillSign", [saved], formValues={"group": "Off"})
    with pikepdf.open(io.BytesIO(next(iter(outputs.values())))) as pdf:
        assert pdf.Root.AcroForm.Fields[0].V == "/Off"
        assert all(widget.AS == "/Off" for widget in pdf.Root.AcroForm.Fields[0].Kids)


def test_checkbox_current_value_can_differ_from_default(pdf3):
    data = result_form(pdf3, [field("checkbox", "agree", value=False, defaultValue=True)])
    fields = pypdf.PdfReader(io.BytesIO(data)).get_fields()
    assert fields["agree"]["/V"] == "/Off"
    assert fields["agree"]["/DV"] == "/Yes"


@pytest.mark.parametrize("maximum", [float("inf"), float("nan"), 4.5, -1, 100001])
def test_text_maximum_length_rejects_invalid_numbers(pdf3, maximum):
    with pytest.raises(TaskError, match="length"):
        result_form(pdf3, [field("text", "code", maxLength=maximum)])


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_generated_choice_appearance_renders_inside_displayed_rectangle(angle):
    import pypdfium2 as pdfium
    import numpy as np
    buffer = io.BytesIO()
    with pikepdf.new() as blank:
        blank.add_blank_page(page_size=(400, 600))
        blank.save(buffer)
    saved = store(buffer.getvalue(), "blank.pdf")
    data = result_form(saved, [field("dropdown", "choice", options=["Visible choice"], value="Visible choice")], pageOrder=[f"1:{angle}"])
    with pdfium.PdfDocument(data) as doc:
        doc.init_forms()
        page = doc[0]
        bitmap = page.render(scale=1)
        image = np.array(bitmap.to_pil().convert("L"))
        bitmap.close()
        page.close()
    height = image.shape[0]
    expected = image[height - 160:height - 100, 60:260]
    assert expected.min() < 100
    outside = image.copy()
    outside[height - 162:height - 98, 58:262] = 255
    assert outside.min() > 240
