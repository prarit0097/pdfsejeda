"""PDF editor save: applies the operation arrays sent by the browser editor.

All coordinates are PDF points in the page's *displayed* space (after rotation),
origin bottom-left — the same space `draw.stamp` draws in.

Page structure comes first:
  pageOrder: ["3:0", "-1:0", "1:90", "-1:0:595x842", …]  original page (1-based) or -1 for a
             new blank page, plus extra clockwise rotation (a multiple of 90). A blank page may
             carry its unrotated size as a third part "WxH" (otherwise it copies the size of
             the page before it). Ops then use `page`/`pages` = 1-based positions in this final
             order. A page listed twice is copied (without its annotations).
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
  appendFormFieldOperations {page, kind text|checkbox|dropdown|listbox|radio, name, boundingBox, value, defaultValue, options, multiSelect, exportValue, multiline, maxLength, comb, required, fontSize}
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


def _page_order(raw) -> list[str]:
    if isinstance(raw, str):
        raw = raw.strip()
        try:
            raw = json.loads(raw) if raw.startswith("[") else raw.split(",")
        except ValueError:
            raise TaskError("Invalid page order") from None
    if not isinstance(raw, (list, tuple)):
        raise TaskError("Invalid page order")
    return [str(x).strip() for x in raw if str(x).strip()]


def _parse_entry(entry: str):
    parts = entry.split(":")
    try:
        orig, rot = int(float(parts[0])), int(float(parts[1])) if len(parts) > 1 and parts[1] else 0
        size = None
        if len(parts) > 2 and parts[2]:
            w, h = (float(v) for v in parts[2].lower().split("x"))
            if not (1 <= w <= 14400 and 1 <= h <= 14400):
                raise ValueError
            size = (w, h)
    except (ValueError, IndexError):
        raise TaskError(f"Invalid page order entry '{entry}'") from None
    if rot % 90 or len(parts) > 3:
        raise TaskError(f"Invalid page order entry '{entry}'")
    return orig, rot, size


def _build_pages(ctx, src: pikepdf.Pdf) -> pikepdf.Pdf:
    order = ctx.params.get("pageOrder")
    dst = pikepdf.new()
    total = len(src.pages)
    if order:
        used = set()
        for entry in _page_order(order):
            orig, rot, blank_size = _parse_entry(entry)
            if orig == -1:
                if blank_size:
                    w, h = blank_size
                else:
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
        try:
            data = base64.b64decode(re.sub(r"\s+", "", m.group(1)))
        except ValueError:
            raise TaskError("An image in the document could not be read") from None
    else:
        try:
            data = files.get(spec).path.read_bytes()
        except (FileNotFound, ValueError, OSError):
            raise TaskError("An image used in the document has expired. Add it again.") from None
    try:
        pil = Image.open(io.BytesIO(data))
        pil.load()
    except Exception:  # not an image, truncated, or a decompression bomb
        raise TaskError("An image in the document could not be read") from None
    if pil.mode == "P" and "transparency" in pil.info or pil.mode in ("LA", "PA", "RGBa", "La"):
        pil = pil.convert("RGBA")
    elif pil.mode not in ("RGB", "RGBA", "L"):
        pil = pil.convert("RGBA" if "A" in pil.mode else "RGB")
    return ImageReader(pil)


def _draw_text_block(c, text, x, y, font, size, color, bold, italic, line_height=None):
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").split("\n")
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


def _appearance(pdf, w, h, ops: bytes, resources=None, matrix=None):
    stream = pdf.make_stream(ops, Type=Name.XObject, Subtype=Name.Form, BBox=[0, 0, w, h],
                             Resources=resources or pikepdf.Dictionary())
    if matrix:
        stream.Matrix = pikepdf.Array(matrix)
    return stream


def _field_string(value, limit=4096):
    """Bound user strings and remove control characters before building appearances."""
    return "".join(c for c in str(value if value is not None else "") if c in "\n\t" or ord(c) >= 32)[:limit]


def _literal(value):
    return _field_string(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _choice_options(raw):
    if not isinstance(raw, list) or not raw or len(raw) > 500:
        raise TaskError("Choice fields need between 1 and 500 options")
    options = []
    for item in raw:
        if isinstance(item, dict):
            value = _field_string(item.get("value", ""), 1024)
            label = _field_string(item.get("label", value), 1024)
        elif isinstance(item, (str, int, float)):
            value = label = _field_string(item, 1024)
        else:
            raise TaskError("Invalid choice field option")
        if any(v == value for v, _ in options):
            raise TaskError("Choice option values must be unique")
        options.append((value, label))
    return options


def _radio_appearance(w, h, selected=False):
    radius = max(0.1, min(w, h) / 2 - 1)
    x, y = w / 2, h / 2
    def circle(r):
        k = r * 0.55228475
        return (f"{x+r:g} {y:g} m {x+r:g} {y+k:g} {x+k:g} {y+r:g} {x:g} {y+r:g} c "
                f"{x-k:g} {y+r:g} {x-r:g} {y+k:g} {x-r:g} {y:g} c "
                f"{x-r:g} {y-k:g} {x-k:g} {y-r:g} {x:g} {y-r:g} c "
                f"{x+k:g} {y-r:g} {x+r:g} {y-k:g} {x+r:g} {y:g} c")
    ops = "q 0.4 G 1 w " + circle(radius) + " S"
    if selected:
        ops += " 0 g " + circle(radius * 0.5) + " f"
    return (ops + " Q").encode("ascii")


def _add_form_field(pdf, op, fields: list, font_ref):
    p = int(_f(op.get("page"), 1))
    if not 1 <= p <= len(pdf.pages):
        return
    page = pdf.pages[p - 1]
    b = op.get("boundingBox") or {}
    rect = _to_user_rect(page, *(_f(b.get(k)) for k in ("left", "bottom", "right", "top")))
    rot = rotation(page)
    w, h = float(rect[2] - rect[0]), float(rect[3] - rect[1])
    if rot in (90, 270):
        w, h = h, w
    if not all(math.isfinite(n) and n > 0 for n in (w, h)):
        raise TaskError("Form fields need a positive width and height")
    lin = invert(user_to_visible(page))[:4]
    matrix = [round(v) for v in lin] + [0, 0] if rot else None
    name = re.sub(r"[.\s]+", "_", _field_string(op.get("name") or f"field{len(fields) + 1}", 255))
    kind = op.get("kind", "text")
    if kind not in ("text", "checkbox", "dropdown", "listbox", "radio"):
        raise TaskError("Unsupported form field type")
    existing = list(pdf.Root.AcroForm.Fields) + fields
    same = next((f for f in existing if str(f.get("/T", "")) == name), None)
    if same is not None and not (kind == "radio" and same.get("/FT") == Name.Btn and int(same.get("/Ff", 0)) & 32768):
        raise TaskError("Form field names must be unique (radio buttons may share a group name)")
    size = _f(op.get("fontSize"), 0)
    if not math.isfinite(size) or not 0 <= size <= 300:
        raise TaskError("Invalid form font size")
    flags = 2 if op.get("required") else 0
    common = dict(Type=Name.Annot, Subtype=Name.Widget, Rect=rect, F=4, P=page.obj, T=pikepdf.String(name),
                  MK=pikepdf.Dictionary(BC=[0.4, 0.4, 0.4], **({"R": rot} if rot else {})), Border=[0, 0, 1])
    value = op.get("value", op.get("defaultValue", ""))
    default = op.get("defaultValue", value)
    if kind in ("checkbox", "radio"):
        on = _appearance(pdf, w, h, f"q 0 g BT /ZaDb {min(w, h) * 0.8:.1f} Tf {w * 0.15:.1f} {h * 0.2:.1f} Td (4) Tj ET Q".encode(),
                         pikepdf.Dictionary(Font=pikepdf.Dictionary(ZaDb=pdf.make_indirect(pikepdf.Dictionary(
                             Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.ZapfDingbats)))), matrix)
        off = _appearance(pdf, w, h, b"", None, matrix)
        if kind == "radio":
            on = _appearance(pdf, w, h, _radio_appearance(w, h, True), None, matrix)
            off = _appearance(pdf, w, h, _radio_appearance(w, h), None, matrix)
            common["Border"] = [0, 0, 0]
        export = _field_string(op.get("exportValue") or "Yes", 128).lstrip("/") if kind == "radio" else "Yes"
        if not export or export == "Off":
            raise TaskError("Radio export value must be nonempty and different from Off")
        def checked(v):
            return v is True or str(v).lstrip("/") == export or (kind == "checkbox" and str(v).lower() in ("true", "on", "yes", "1", "/yes"))
        state = Name("/" + export) if checked(value) else Name.Off
        default_state = Name("/" + export) if checked(default) else Name.Off
        normal = pikepdf.Dictionary({"/" + export: on, "/Off": off})
        if kind == "radio":
            group = same
            if group is None:
                group = pdf.make_indirect(pikepdf.Dictionary(FT=Name.Btn, Ff=flags | 32768, T=pikepdf.String(name),
                                                            Kids=pikepdf.Array(), V=Name.Off, DV=Name.Off))
                fields.append(group)
            else:
                group.Ff = int(group.get("/Ff", 0)) | flags
            if any("/" + export in child.AP.N for child in group.Kids):
                raise TaskError("Radio buttons in a group need unique export values")
            if state != Name.Off:
                for child in group.Kids:
                    child.AS = Name.Off
                group.V = state
            if default_state != Name.Off:
                group.DV = default_state
            del common["T"]
            field = _add_annot(pdf, page, pikepdf.Dictionary(Parent=group, AS=state, AP=pikepdf.Dictionary(N=normal), **common))
            group.Kids.append(field)
            return
        field = _add_annot(pdf, page, pikepdf.Dictionary(
            FT=Name.Btn, Ff=flags, V=state, DV=default_state, AS=state,
            AP=pikepdf.Dictionary(N=normal), DA=pikepdf.String("/ZaDb 0 Tf 0 g"), **common))
    else:
        da = f"/Helv {size:g} Tf 0 g" if size else "/Helv 0 Tf 0 g"
        fs = size or min(12, h * 0.7)
        resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=font_ref))
        field_type, extra = Name.Tx, {}
        if kind in ("dropdown", "listbox"):
            options = _choice_options(op.get("options"))
            multiple = kind == "listbox" and bool(op.get("multiSelect"))
            flags |= 131072 if kind == "dropdown" else (2097152 if multiple else 0)
            def selection(v):
                selected = [_field_string(x, 1024) for x in v] if isinstance(v, list) else [_field_string(v, 1024)]
                if not multiple and len(selected) > 1:
                    raise TaskError("This choice field accepts one value")
                if any(x not in {val for val, _ in options} for x in selected if x):
                    raise TaskError("Choice default value must match an option")
                return [val for val, _ in options if val in selected]
            chosen, defaults = selection(value), selection(default)
            value = pikepdf.Array([pikepdf.String(x) for x in chosen]) if multiple else pikepdf.String(chosen[0] if chosen else "")
            default = pikepdf.Array([pikepdf.String(x) for x in defaults]) if multiple else pikepdf.String(defaults[0] if defaults else "")
            field_type = Name.Ch
            extra["Opt"] = pikepdf.Array([pikepdf.Array([pikepdf.String(v), pikepdf.String(label)]) for v, label in options])
            if chosen:
                extra["I"] = pikepdf.Array([i for i, (v, _) in enumerate(options) if v in chosen])
            lines = [(label, v in chosen) for v, label in options] if kind == "listbox" else [(next((label for v, label in options if v in chosen), ""), False)]
        else:
            value, default = _field_string(value), _field_string(default)
            raw_length = _f(op.get("maxLength"), 0)
            if not math.isfinite(raw_length) or not float(raw_length).is_integer():
                raise TaskError("Maximum field length must be an integer")
            max_length = int(raw_length)
            if max_length < 0 or max_length > 100000:
                raise TaskError("Maximum field length must be between 1 and 100000")
            if max_length:
                extra["MaxLen"] = max_length
                value, default = value[:max_length], default[:max_length]
            if op.get("comb"):
                if not max_length or op.get("multiline"):
                    raise TaskError("Comb fields need a maximum length and cannot be multiline")
                flags |= 16777216
            if op.get("multiline"):
                flags |= 4096
            lines = [(line, False) for line in (value.splitlines() if op.get("multiline") else [value.split("\n")[0]])]
            value, default = pikepdf.String(value), pikepdf.String(default)
        commands = [f"/Tx BMC q 0 0 {w:g} {h:g} re W n"]
        for i, (line, selected) in enumerate(lines):
            y = h - fs - 2 - i * fs * 1.2 if kind == "listbox" or op.get("multiline") else max(2, (h - fs) / 2 + fs * 0.2)
            if y < -fs:
                break
            if selected:
                commands.append(f"0.2 0.4 0.8 rg 0 {y - 2:g} {w:g} {fs * 1.2:g} re f")
            if op.get("comb") and kind == "text":
                cell = w / extra["MaxLen"]
                for j, char in enumerate(line):
                    commands.append(f"BT /Helv {fs:g} Tf 0 g {j * cell + cell * 0.25:g} {y:g} Td ({_literal(char)}) Tj ET")
            else:
                commands.append(f"BT /Helv {fs:g} Tf {'1 g' if selected else '0 g'} 2 {y:g} Td ({_literal(line)}) Tj ET")
        commands.append("Q EMC")
        field = _add_annot(pdf, page, pikepdf.Dictionary(
            FT=field_type, Ff=flags, DA=pikepdf.String(da), V=value, DV=default,
            AP=pikepdf.Dictionary(N=_appearance(pdf, w, h, "\n".join(commands).encode("latin-1", "replace"), resources, matrix)),
            **extra, **common))
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
    from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject

    reader = pypdf.PdfReader(str(path))
    writer = pypdf.PdfWriter(clone_from=reader)
    if "/AcroForm" not in writer._root_object:
        return
    norm = {}
    for k, v in values.items():
        if isinstance(v, bool):
            v = "/Yes" if v else "/Off"
        norm[str(k)] = v
    def clear_radio_values(nodes):
        for reference in nodes:
            node = reference.get_object()
            if node.get("/FT") == "/Btn" and int(node.get("/Ff", 0)) & 32768 and _full_name(node) in norm:
                node[NameObject("/V")] = NameObject("/Off")
            clear_radio_values(node.get("/Kids", []))
    clear_radio_values(writer._root_object["/AcroForm"].get("/Fields", []))
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
                is_radio = bool(int(node.get("/Ff", 0)) & 32768)
                same = str(v).lstrip("/") == str(on).lstrip("/")
                want_on = same if is_radio else (same or str(v).lower() in ("/yes", "true", "on", "yes", "1"))
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
            # pypdf's appearance builder joins /Opt as strings; valid [export,
            # label] pairs crash listbox filling and display export codes for
            # dropdowns. Render with labels temporarily, then restore the PDF's
            # canonical export values, option pairs and selection indices.
            restore = []
            for a in annots:
                a = a.get_object()
                node = a if "/T" in a else a.get("/Parent", a).get_object()
                n = _full_name(node) if "/T" in node else None
                if n not in page_vals or node.get("/FT") != "/Ch":
                    continue
                options = node.get("/Opt", [])
                pairs = [(str(x[0]), str(x[1])) if isinstance(x, list) else (str(x), str(x)) for x in options]
                requested = page_vals[n]
                selected = [str(x) for x in requested] if isinstance(requested, list) else [str(requested)]
                label_map = dict(pairs)
                if any(v not in label_map and v for v in selected) and not int(node.get("/Ff", 0)) & 262144:
                    raise TaskError("Choice value must match an available option")
                if len(selected) > 1 and not int(node.get("/Ff", 0)) & 2097152:
                    raise TaskError("This choice field accepts one value")
                restore.append((node, options, selected, isinstance(requested, list), pairs))
                node[NameObject("/Opt")] = ArrayObject(TextStringObject(label) for _, label in pairs)
                labels = [label_map.get(v, v) for v in selected]
                page_vals[n] = labels if isinstance(requested, list) else labels[0]
            writer.update_page_form_field_values(page, {k: [str(x) for x in v] if isinstance(v, list) else str(v) for k, v in page_vals.items()}, auto_regenerate=False)
            for node, options, selected, multiple, pairs in restore:
                node[NameObject("/Opt")] = options
                node[NameObject("/V")] = ArrayObject(TextStringObject(x) for x in selected) if multiple else TextStringObject(selected[0])
                indices = [i for i, (v, _) in enumerate(pairs) if v in selected]
                if indices:
                    node[NameObject("/I")] = ArrayObject(NumberObject(i) for i in indices)
    writer.set_need_appearances_writer(False)
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
        try:
            values = json.loads(values or "{}")
        except ValueError:
            raise TaskError("Invalid form values") from None
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
              tagline="Create fillable PDFs with text, checkbox, radio and choice fields.",
              keywords="form fields fillable acroform create", **EDITOR))


def _alias(task_type, target):
    from .registry import alias

    alias(task_type, target)


_alias("pdfToDoc", "pdfToOfficeWord")
_alias("pdfToExcel", "pdfToExcelNext")
