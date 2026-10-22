"""PDF editor save: applies the operation arrays sent by the browser editor.

All coordinates are PDF points in the page's *displayed* space (after rotation),
origin bottom-left — the same space `draw.stamp` draws in.

Page structure comes first:
  pageOrder: ["3:0", "-1:0", "1:90", …]  original page (1-based) or -1 for a new blank
             page, plus extra clockwise rotation. Ops then use `page`/`pages` = 1-based
             positions in this final order.
  Without pageOrder, deletePageOperations (original numbers), insertPageOperations
  and rotatePageOperations are applied, in that order.

Operation arrays (each entry is an object, or a JSON string of one):
  editTextOperations      {page, area{x,y,width,height}, text, font, fontSize, color, bold, italic, position{x,y}, lineHeight}
  shapeOperations         {pages, position{x,y}, width, height, shape rectangle|ellipse, borderWidth, borderColor, backgroundColor, opacity}
  highlightTextOperations {page, boundingBoxes[{left,top,bottom,right}], color, kind highlight|strikethrough|underline}
  imageOperations         {pages, position{x,y}, width, height, rotation, image (data URL or file id), opacity}
  appendDraw              {page, inklist[[x,y,x,y…]], color, lineSize}
  appendLine              {page, points[x1,y1,x2,y2], color, lineSize, kind line|arrow}
  appendTextOperations    {pages, text, font, fontSize, position{x,y} (first baseline), lineHeight, color, bold, italic}
  appendLinkOperations    {page, boundingBoxes[…], kind uri|page, href}
  appendFormFieldOperations {page, kind text|checkbox, name, boundingBox, value, multiline, required, fontSize}
  formValues              {fieldName: value}
"""
from __future__ import annotations

import base64
import io
import json
import math
import re

import pikepdf
from pikepdf import Name

from ..jobs import TaskError
from ..storage import FileNotFound, files
from .common import open_pdf, output_name, rotation, save_pdf
from .draw import font_for, hex_to_rgb, invert, new_blank_page, stamp, user_to_visible, visible_size
from .registry import Tool, register

DRAW_ARRAYS = ["editTextOperations", "shapeOperations", "highlightTextOperations", "imageOperations",
               "appendDraw", "appendLine", "appendTextOperations"]


def _ops(ctx, name) -> list[dict]:
    raw = ctx.params.get(name) or []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    out = []
    for item in raw:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                raise TaskError(f"Invalid editor data in {name}") from None
        if isinstance(item, dict):
            out.append(item)
    return out


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _page_list(spec, total: int) -> list[int]:
    from ..pages import PageSelectionError, parse_pages

    if spec in (None, ""):
        return []
    try:
        return parse_pages(spec, total)
    except PageSelectionError:
        return []


# ---------------------------------------------------------------------------
# page structure


def _build_pages(ctx, src: pikepdf.Pdf) -> pikepdf.Pdf:
    order = ctx.params.get("pageOrder")
    dst = pikepdf.new()
    total = len(src.pages)
    if order:
        used = set()
        for entry in order:
            try:
                orig, rot = (int(float(x)) for x in str(entry).split(":"))
            except ValueError:
                raise TaskError(f"Invalid page order entry '{entry}'") from None
            if orig == -1:
                ref = dst.pages[-1] if len(dst.pages) else src.pages[0]
                w, h = visible_size(ref)
                page = new_blank_page(dst, w, h)
            else:
                if not 1 <= orig <= total:
                    raise TaskError(f"Page {orig} does not exist")
                if orig in used:
                    d = src.make_indirect(pikepdf.Dictionary({k: v for k, v in src.pages[orig - 1].obj.items() if k not in ("/Parent", "/Annots")}))
                    dst.pages.append(pikepdf.Page(d))
                else:
                    dst.pages.append(src.pages[orig - 1])
                    used.add(orig)
                page = dst.pages[-1]
            if rot % 360:
                page.obj.Rotate = (rotation(page) + rot) % 360
        if not len(dst.pages):
            raise TaskError("The document must keep at least one page")
        _carry_acroform(src, dst)
        return dst
    deleted = {int(_f(op.get("page"))) for op in _ops(ctx, "deletePageOperations")}
    for i in range(total):
        if i + 1 not in deleted:
            dst.pages.append(src.pages[i])
    if not len(dst.pages):
        raise TaskError("The document must keep at least one page")
    for op in sorted(_ops(ctx, "insertPageOperations"), key=lambda o: _f(o.get("page"))):
        pos = max(1, min(int(_f(op.get("page"), 1)), len(dst.pages) + 1))
        ref = dst.pages[min(pos - 1, len(dst.pages) - 1)]
        w, h = visible_size(ref)
        new_blank_page(dst, w, h, index=pos - 1)
    for op in _ops(ctx, "rotatePageOperations"):
        for p in _page_list(op.get("pages", op.get("page")), len(dst.pages)):
            page = dst.pages[p - 1]
            page.obj.Rotate = (rotation(page) + int(_f(op.get("degrees")))) % 360
    _carry_acroform(src, dst)
    return dst


def _carry_acroform(src, dst):
    if "/AcroForm" not in src.Root:
        return
    from .organize import _collect_copied_fields

    fields = _collect_copied_fields(dst, range(len(dst.pages)))
    if fields:
        form = src.Root.AcroForm
        acro = dst.copy_foreign(form if form.is_indirect else src.make_indirect(form))
        acro.Fields = pikepdf.Array(fields)
        dst.Root.AcroForm = acro


# ---------------------------------------------------------------------------
# drawing


def _image_reader(spec: str):
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    if not spec:
        return None
    if spec.startswith("data:"):
        m = re.match(r"data:image/[\w.+-]+;base64,(.*)", spec, re.S)
        if not m:
            return None
        data = base64.b64decode(m.group(1))
    else:
        try:
            data = files.get(spec).path.read_bytes()
        except FileNotFound:
            raise TaskError("An image used in the document has expired. Add it again.") from None
    pil = Image.open(io.BytesIO(data))
    pil.load()
    if pil.mode not in ("RGB", "RGBA", "L", "LA"):
        pil = pil.convert("RGBA")
    return ImageReader(pil)


def _draw_text_block(c, text, x, y, font, size, color, bold, italic, line_height=None):
    lines = str(text).split("\n")
    lh = line_height or size * 1.2
    c.setFillColorRGB(*hex_to_rgb(color))
    for i, line in enumerate(lines):
        c.setFont(font_for(font, line, bold, italic), size)
        c.drawString(x, y - i * lh, line)


def _arrow_head(c, x1, y1, x2, y2, size):
    ang = math.atan2(y2 - y1, x2 - x1)
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(x2 - size * math.cos(ang - 0.45), y2 - size * math.sin(ang - 0.45))
    p.lineTo(x2 - size * math.cos(ang + 0.45), y2 - size * math.sin(ang + 0.45))
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _make_drawer(items: list[tuple[str, dict]]):
    images = {}

    def draw(c, w, h):
        for kind, op in items:
            c.saveState()
            if kind == "editTextOperations":
                a = op.get("area") or {}
                c.setFillColorRGB(1, 1, 1)
                c.rect(_f(a.get("x")), _f(a.get("y")), _f(a.get("width")), _f(a.get("height")), stroke=0, fill=1)
                pos = op.get("position") or {}
                if str(op.get("text", "")).strip():
                    _draw_text_block(c, op.get("text", ""), _f(pos.get("x"), _f(a.get("x"))), _f(pos.get("y"), _f(a.get("y")) + 2),
                                     op.get("font"), _f(op.get("fontSize"), 11) or 11, op.get("color"), bool(op.get("bold")),
                                     bool(op.get("italic")), _f(op.get("lineHeight"), 0) or None)
            elif kind == "shapeOperations":
                pos = op.get("position") or {}
                x, y, sw, sh = _f(pos.get("x")), _f(pos.get("y")), _f(op.get("width")), _f(op.get("height"))
                bw = _f(op.get("borderWidth"), 1)
                fill = op.get("backgroundColor")
                stroke = op.get("borderColor") if bw > 0 else None
                c.setFillAlpha(_f(op.get("opacity"), 1))
                c.setStrokeAlpha(_f(op.get("opacity"), 1))
                if fill:
                    c.setFillColorRGB(*hex_to_rgb(fill))
                if stroke:
                    c.setStrokeColorRGB(*hex_to_rgb(stroke))
                    c.setLineWidth(bw)
                if op.get("shape") == "ellipse":
                    c.ellipse(x, y, x + sw, y + sh, stroke=1 if stroke else 0, fill=1 if fill else 0)
                else:
                    c.rect(x, y, sw, sh, stroke=1 if stroke else 0, fill=1 if fill else 0)
            elif kind == "highlightTextOperations":
                col = hex_to_rgb(op.get("color"), (1, 0.9, 0.2))
                for b in op.get("boundingBoxes") or []:
                    left, right, top, bottom = (_f(b.get(k)) for k in ("left", "right", "top", "bottom"))
                    hk = op.get("kind", "highlight")
                    if hk == "highlight":
                        c.setFillColorRGB(*col)
                        c.setFillAlpha(0.4)
                        c.rect(left, bottom, right - left, top - bottom, stroke=0, fill=1)
                    else:
                        c.setStrokeColorRGB(*col)
                        c.setLineWidth(max(1, (top - bottom) * 0.08))
                        yy = (top + bottom) / 2 if hk == "strikethrough" else bottom + (top - bottom) * 0.08
                        c.line(left, yy, right, yy)
            elif kind == "imageOperations":
                key = op.get("image", "")
                if key not in images:
                    images[key] = _image_reader(key)
                img = images[key]
                if img is not None:
                    pos = op.get("position") or {}
                    x, y, iw, ih = _f(pos.get("x")), _f(pos.get("y")), _f(op.get("width")), _f(op.get("height"))
                    c.setFillAlpha(_f(op.get("opacity"), 1))
                    c.translate(x + iw / 2, y + ih / 2)
                    c.rotate(-_f(op.get("rotation")))
                    c.drawImage(img, -iw / 2, -ih / 2, iw, ih, mask="auto")
            elif kind == "appendDraw":
                c.setStrokeColorRGB(*hex_to_rgb(op.get("color")))
                c.setLineWidth(_f(op.get("lineSize"), 2))
                c.setLineCap(1)
                c.setLineJoin(1)
                for stroke_pts in op.get("inklist") or []:
                    pts = [_f(v) for v in stroke_pts]
                    if len(pts) < 4:
                        continue
                    p = c.beginPath()
                    p.moveTo(pts[0], pts[1])
                    for i in range(2, len(pts) - 1, 2):
                        p.lineTo(pts[i], pts[i + 1])
                    c.drawPath(p, stroke=1, fill=0)
            elif kind == "appendLine":
                x1, y1, x2, y2 = (_f(v) for v in (op.get("points") or [0, 0, 0, 0])[:4])
                col = hex_to_rgb(op.get("color"))
                lw = _f(op.get("lineSize"), 2)
                c.setStrokeColorRGB(*col)
                c.setFillColorRGB(*col)
                c.setLineWidth(lw)
                c.setLineCap(1)
                if op.get("kind") == "arrow":
                    head = max(6, lw * 4)
                    ang = math.atan2(y2 - y1, x2 - x1)
                    c.line(x1, y1, x2 - head * 0.7 * math.cos(ang), y2 - head * 0.7 * math.sin(ang))
                    _arrow_head(c, x1, y1, x2, y2, head)
                else:
                    c.line(x1, y1, x2, y2)
            elif kind == "appendTextOperations":
                pos = op.get("position") or {}
                size = _f(op.get("fontSize"), 12) or 12
                _draw_text_block(c, op.get("text", ""), _f(pos.get("x")), _f(pos.get("y")), op.get("font"), size,
                                 op.get("color"), bool(op.get("bold")), bool(op.get("italic")), _f(op.get("lineHeight"), 0) or None)
            c.restoreState()

    return draw


# ---------------------------------------------------------------------------
# annotations and form fields (need user-space rectangles)


def _to_user_rect(page, left, bottom, right, top):
    m = invert(user_to_visible(page))
    pts = [(left, bottom), (right, top), (left, top), (right, bottom)]
    xs = [m[0] * x + m[2] * y + m[4] for x, y in pts]
    ys = [m[1] * x + m[3] * y + m[5] for x, y in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _add_annot(pdf, page, annot):
    annot = pdf.make_indirect(annot)
    if "/Annots" not in page.obj:
        page.obj.Annots = pikepdf.Array()
    page.obj.Annots.append(annot)
    return annot


def _add_link(pdf, op):
    total = len(pdf.pages)
    p = int(_f(op.get("page"), 1))
    if not 1 <= p <= total:
        return
    page = pdf.pages[p - 1]
    href = str(op.get("href") or "").strip()
    if not href:
        return
    for b in op.get("boundingBoxes") or []:
        rect = _to_user_rect(page, *(_f(b.get(k)) for k in ("left", "bottom", "right", "top")))
        if op.get("kind") == "page" or re.fullmatch(r"\d+", href):
            target = int(href)
            if not 1 <= target <= total:
                continue
            action = dict(Dest=pikepdf.Array([pdf.pages[target - 1].obj, Name.Fit]))
        else:
            if not re.match(r"^(https?:|mailto:|tel:)", href, re.I):
                href = "https://" + href
            action = dict(A=pikepdf.Dictionary(S=Name.URI, URI=pikepdf.String(href)))
        _add_annot(pdf, page, pikepdf.Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=rect, Border=[0, 0, 0], **action))


def _appearance(pdf, w, h, ops: bytes, resources=None):
    return pdf.make_stream(ops, Type=Name.XObject, Subtype=Name.Form, BBox=[0, 0, w, h],
                           Resources=resources or pikepdf.Dictionary())


def _add_form_field(pdf, op, fields: list, font_ref):
    p = int(_f(op.get("page"), 1))
    if not 1 <= p <= len(pdf.pages):
        return
    page = pdf.pages[p - 1]
    b = op.get("boundingBox") or {}
    rect = _to_user_rect(page, *(_f(b.get(k)) for k in ("left", "bottom", "right", "top")))
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    name = re.sub(r"[.\s]+", "_", str(op.get("name") or f"field{len(fields) + 1}"))
    kind = op.get("kind", "text")
    size = _f(op.get("fontSize"), 0)
    flags = 2 if op.get("required") else 0
    common = dict(Type=Name.Annot, Subtype=Name.Widget, Rect=rect, F=4, P=page.obj, T=pikepdf.String(name),
                  MK=pikepdf.Dictionary(BC=[0.4, 0.4, 0.4]), Border=[0, 0, 1])
    if kind == "checkbox":
        on = _appearance(pdf, w, h, f"q 0 g BT /ZaDb {min(w, h) * 0.8:.1f} Tf {w * 0.15:.1f} {h * 0.2:.1f} Td (4) Tj ET Q".encode(),
                         pikepdf.Dictionary(Font=pikepdf.Dictionary(ZaDb=pdf.make_indirect(pikepdf.Dictionary(
                             Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats)))))
        off = _appearance(pdf, w, h, b"")
        checked = str(op.get("value", "")).lower() in ("true", "on", "yes", "1")
        field = _add_annot(pdf, page, pikepdf.Dictionary(
            FT=Name.Btn, Ff=flags, V=Name.Yes if checked else Name.Off, AS=Name.Yes if checked else Name.Off,
            AP=pikepdf.Dictionary(N=pikepdf.Dictionary(Yes=on, Off=off)), DA=pikepdf.String("/ZaDb 0 Tf 0 g"), **common))
    else:
        if op.get("multiline"):
            flags |= 4096
        da = f"/Helv {size:g} Tf 0 g" if size else "/Helv 0 Tf 0 g"
        value = str(op.get("value") or "")
        fs = size or min(12, h * 0.7)
        ap_ops = b"/Tx BMC EMC"
        if value:
            safe = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").split("\n")[0]
            ap_ops = f"/Tx BMC q BT /Helv {fs:.1f} Tf 0 g 2 {max(2, (h - fs) / 2 + fs * 0.2):.1f} Td ({safe}) Tj ET Q EMC".encode("latin-1", "replace")
        field = _add_annot(pdf, page, pikepdf.Dictionary(
            FT=Name.Tx, Ff=flags, DA=pikepdf.String(da), V=pikepdf.String(value),
            AP=pikepdf.Dictionary(N=_appearance(pdf, w, h, ap_ops, pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font_ref)))),
            **common))
        if op.get("maxLength"):
            field.MaxLen = int(_f(op.get("maxLength")))
    fields.append(field)


def _ensure_acroform(pdf):
    if "/AcroForm" not in pdf.Root:
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
    acro = pdf.Root.AcroForm
    if "/Fields" not in acro:
        acro.Fields = pikepdf.Array()
    helv = None
    dr = acro.get("/DR")
    if dr is not None and "/Font" in dr and "/Helv" in dr.Font:
        helv = dr.Font.Helv
    if helv is None:
        helv = pdf.make_indirect(pikepdf.Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica,
                                                    Encoding=Name.WinAnsiEncoding))
        acro.DR = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=helv))
    if "/DA" not in acro:
        acro.DA = pikepdf.String("/Helv 0 Tf 0 g")
    return acro, helv


def _fill_form(path, values: dict):
    """Set field values with pypdf, which also regenerates text appearances."""
    import pypdf
    from pypdf.generic import NameObject

    reader = pypdf.PdfReader(str(path))
    writer = pypdf.PdfWriter(clone_from=reader)
    if "/AcroForm" not in writer._root_object:
        return
    norm = {}
    for k, v in values.items():
        if isinstance(v, bool):
            v = "/Yes" if v else "/Off"
        elif isinstance(v, list):
            v = v[0] if len(v) == 1 else v
        norm[str(k)] = v
    for page in writer.pages:
        annots = page.get("/Annots") or []
        names = set()
        for a in annots:
            a = a.get_object()
            node = a
            while "/T" not in node and "/Parent" in node:
                node = node["/Parent"].get_object()
            if "/T" in node:
                names.add(_full_name(node))
        page_vals = {}
        for n in names:
            if n in norm:
                page_vals[n] = norm[n]
        if not page_vals:
            continue
        # checkboxes: map True to the widget's real "on" state name
        for a in annots:
            a = a.get_object()
            node = a if "/T" in a else a.get("/Parent", a).get_object()
            n = _full_name(node) if "/T" in node else None
            if n in page_vals and node.get("/FT") == "/Btn":
                v = page_vals[n]
                ap = a.get("/AP", {}).get("/N", {})
                on = next((k for k in ap.keys() if k != "/Off"), "/Yes")
                want_on = str(v).lower() in ("/yes", "true", "on", "yes", "1") or str(v) == on or str(v).lstrip("/") == str(on).lstrip("/")
                state = on if want_on else "/Off"
                a[NameObject("/AS")] = NameObject(state)
                if want_on or "/Kids" not in node:  # radio groups: only the chosen widget sets the value
                    node[NameObject("/V")] = NameObject(state)
        for a in annots:
            a = a.get_object()
            node = a if "/T" in a else a.get("/Parent", a).get_object()
            if "/T" in node and node.get("/FT") == "/Btn":
                page_vals.pop(_full_name(node), None)
        if page_vals:
            writer.update_page_form_field_values(page, {k: str(v) for k, v in page_vals.items()}, auto_regenerate=False)
    writer.set_need_appearances_writer(True)
    with open(path, "wb") as fh:
        writer.write(fh)


def _full_name(node) -> str:
    parts = []
    while node is not None:
        if "/T" in node:
            parts.append(str(node["/T"]))
        node = node.get("/Parent")
        node = node.get_object() if node is not None else None
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------


def edit(ctx):
    if len(ctx.inputs) != 1:
        raise TaskError("The editor works on one PDF at a time")
    inp = ctx.inputs[0]
    src = open_pdf(inp)
    pdf = _build_pages(ctx, src)
    total = len(pdf.pages)
    per_page: dict[int, list] = {}
    for name in DRAW_ARRAYS:
        for op in _ops(ctx, name):
            pages = _page_list(op.get("pages", op.get("page")), total)
            except_pages = {int(_f(x)) for x in op.get("exceptPages") or []}
            for p in pages:
                if p not in except_pages:
                    per_page.setdefault(p, []).append((name, op))
    for p, items in sorted(per_page.items()):
        ctx.check_cancelled()
        stamp(pdf, pdf.pages[p - 1], _make_drawer(items))
    for op in _ops(ctx, "appendLinkOperations"):
        _add_link(pdf, op)
    new_fields = _ops(ctx, "appendFormFieldOperations")
    if new_fields:
        acro, helv = _ensure_acroform(pdf)
        made = []
        for op in new_fields:
            _add_form_field(pdf, op, made, helv)
        for f in made:
            acro.Fields.append(f)
    out = ctx.output(output_name(ctx, inp))
    save_pdf(pdf, out)
    values = ctx.params.get("formValues")
    if isinstance(values, str):
        values = json.loads(values or "{}")
    if isinstance(values, dict) and values:
        _fill_form(out, values)
    if ctx.flag("flattenForms"):
        with pikepdf.open(out, allow_overwriting_input=True) as done:
            try:
                done.generate_appearance_streams()
            except Exception:
                pass
            done.flatten_annotations("all")
            if "/AcroForm" in done.Root:
                del done.Root["/AcroForm"]
            done.save(out)
    ctx.remark("Your changes were saved")


EDITOR = dict(handler=edit, multiple=False, max_files=1, template="editor.html", category="edit")

register(Tool(type="edit", slug="pdf-editor", title="Edit PDF", icon="edit", popular=True,
              tagline="Add and change text, images, shapes, links, highlights and signatures — right on the page.",
              keywords="editor change text add image annotate whiteout write", **EDITOR))
register(Tool(type="fillSign", slug="sign-pdf", title="Fill & sign", icon="sign", popular=True,
              tagline="Fill in PDF forms and add your signature, initials or the date.",
              keywords="signature sign fill form esign initials", **EDITOR))
register(Tool(type="editForms", slug="pdf-forms", title="Create fillable form", icon="form",
              tagline="Add text boxes and checkboxes to turn any PDF into a fillable form.",
              keywords="form fields fillable acroform create", **EDITOR))


def _alias(task_type, target):
    from .registry import alias

    alias(task_type, target)


_alias("pdfToDoc", "pdfToOfficeWord")
_alias("pdfToExcel", "pdfToExcelNext")
