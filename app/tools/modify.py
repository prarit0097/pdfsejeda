"""Optimize & page-layout tools: compress, crop, resize, n-up, flip, grayscale,
deskew, flatten, repair."""
from __future__ import annotations

import io
import math

import pikepdf
from pikepdf import Name, PdfImage

from ..jobs import TaskError
from .common import PAGE_SIZES_PT, UNIT_PT, open_pdf, output_name, page_box, pages_or_error, pdfium_doc, rotation, save_pdf
from .draw import _fmt, invert, mul, new_blank_page, place_page, user_to_visible, visible_size
from .organize import set_visible_crop
from .registry import Opt, Tool, register


def _fmt_size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} KB"


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# image helpers


def iter_image_xobjects(pdf: pikepdf.Pdf):
    """Yield (image_stream, max_display_size_pt) for every distinct image XObject in the document."""
    seen: dict = {}

    def walk(resources, w, h, depth=0):
        if resources is None or depth > 8:
            return
        xobjs = resources.get("/XObject")
        if not isinstance(xobjs, pikepdf.Dictionary):
            return
        for _, xo in xobjs.items():
            if not isinstance(xo, pikepdf.Stream):
                continue
            sub = xo.get("/Subtype")
            if sub == Name.Image:
                key = xo.objgen
                if key == (0, 0):
                    continue
                prev = seen.get(key)
                seen[key] = (xo, (max(w, prev[1][0]), max(h, prev[1][1])) if prev else (w, h))
            elif sub == Name.Form:
                walk(xo.get("/Resources"), w, h, depth + 1)

    for page in pdf.pages:
        w, h = visible_size(page)
        walk(page.obj.get("/Resources"), w, h)
    return list(seen.values())


def recompress_image(xo: pikepdf.Stream, quality: int, max_dpi: float | None, display: tuple[float, float],
                     grayscale: bool) -> int:
    """Re-encode one image as JPEG when that makes it smaller. Returns bytes saved."""
    from PIL import Image

    if xo.get("/ImageMask") or int(xo.get("/BitsPerComponent", 8)) < 8:
        return 0
    filt = xo.get("/Filter")
    filters = [str(f) for f in filt] if isinstance(filt, pikepdf.Array) else [str(filt)] if filt else []
    if any(f in ("/JBIG2Decode", "/CCITTFaxDecode", "/JPXDecode") for f in filters):
        return 0
    try:
        old_len = len(xo.read_raw_bytes())
        pil = PdfImage(xo).as_pil_image()
    except Exception:
        return 0
    if pil.mode not in ("RGB", "L", "CMYK"):
        try:
            pil = pil.convert("RGB")
        except Exception:
            return 0
    if grayscale and pil.mode != "L":
        pil = pil.convert("L")
    if max_dpi:
        dw, dh = max(display[0], 1), max(display[1], 1)
        dpi = max(pil.width / (dw / 72), pil.height / (dh / 72))
        if dpi > max_dpi * 1.1:
            k = max_dpi / dpi
            pil = pil.resize((max(1, int(pil.width * k)), max(1, int(pil.height * k))), Image.LANCZOS)
    if pil.mode == "CMYK":
        pil = pil.convert("RGB")
    buf = io.BytesIO()
    pil.save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    if len(data) >= old_len and not grayscale:
        return 0
    xo.write(data, filter=Name.DCTDecode)
    xo.Width, xo.Height = pil.width, pil.height
    xo.ColorSpace = Name.DeviceGray if pil.mode == "L" else Name.DeviceRGB
    xo.BitsPerComponent = 8
    for k in ("/DecodeParms", "/Decode", "/Intent"):
        if k in xo:
            del xo[k]
    return old_len - len(data)


# ---------------------------------------------------------------------------
# compress


def compress(ctx):
    quality = {0.65: 55, 0.8: 72, 1.0: 90}.get(round(ctx.number("imageQuality", 0.8), 2), 72)
    max_dpi = ctx.number("imageDpi", 144) or None
    gray = ctx.param("imageConversion") == "grayscale"
    drop_media = ctx.param("discardMultimedia", "all") == "all"
    fail_if_bigger = ctx.flag("failIfOutputSizeNotReduced")
    total_in = total_out = 0
    for inp in ctx.inputs:
        ctx.check_cancelled()
        before = inp.path.stat().st_size
        pdf = open_pdf(inp)
        for xo, display in iter_image_xobjects(pdf):
            recompress_image(xo, quality, max_dpi, display, gray)
        if drop_media:
            _remove_multimedia(pdf)
        try:
            pdf.remove_unreferenced_resources()
        except Exception:
            pass
        out = ctx.output(output_name(ctx, inp))
        pdf.save(out, compress_streams=True, recompress_flate=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
        after = out.stat().st_size
        if after >= before and not fail_if_bigger:
            out.write_bytes(inp.path.read_bytes())
            after = before
        total_in += before
        total_out += after
    if total_out >= total_in:
        ctx.remark("This file is already well optimized; we couldn't make it smaller.")
    else:
        pct = round(100 * (1 - total_out / total_in))
        ctx.remark(f"Reduced from {_fmt_size(total_in)} to {_fmt_size(total_out)} ({pct}% smaller)")


def _remove_multimedia(pdf):
    media = {Name.RichMedia, Name.Movie, Name.Sound, Name("/Screen")}
    for page in pdf.pages:
        annots = page.obj.get("/Annots")
        if isinstance(annots, pikepdf.Array):
            keep = [a for a in annots if a.get("/Subtype") not in media]
            if len(keep) != len(annots):
                page.obj.Annots = pikepdf.Array(keep)


register(Tool(
    type="compress", slug="compress-pdf", title="Compress PDF", icon="compress", category="optimize", popular=True,
    tagline="Make a PDF smaller by optimizing its images and structure, with the quality you choose.",
    handler=compress, keywords="reduce size shrink optimize smaller",
    options=[
        Opt("imageQuality", "Image quality", "radio", [("0.65", "Smaller file"), ("0.8", "Balanced"), ("1", "Best quality")], "0.8"),
        Opt("imageDpi", "Maximum image resolution", "select", [("72", "72 dpi — screen"), ("100", "100 dpi"), ("144", "144 dpi — recommended"),
            ("200", "200 dpi"), ("300", "300 dpi — print"), ("720", "720 dpi")], "144", advanced=True),
        Opt("imageConversion", "Image colors", "radio", [("none", "Keep colors"), ("grayscale", "Convert to grayscale")], "none", advanced=True),
        Opt("discardMultimedia", "Embedded audio & video", "radio", [("all", "Remove"), ("none", "Keep")], "all", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# crop


def _content_bbox(doc, index: int, threshold: int = 245):
    """Bounding box of non-white content in displayed coordinates (bottom-left origin), or None if blank."""
    import numpy as np

    page = doc[index]
    w, h = page.get_size()  # displayed size in points (pdfium applies /Rotate)
    scale = min(2.0, 1200 / max(w, h))
    img = page.render(scale=scale, grayscale=True).to_numpy()
    if img.ndim == 3:
        img = img[..., 0]
    ink = img < threshold
    rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    if not len(rows):
        return None
    pad = 4
    x0, x1 = cols[0] / scale - pad, (cols[-1] + 1) / scale + pad
    top, bottom = rows[0] / scale - pad, (rows[-1] + 1) / scale + pad
    return float(max(0, x0)), float(max(0, h - bottom)), float(min(w, x1)), float(min(h, h - top))


def crop(ctx):
    mode = ctx.param("cropMode", "auto")
    unit = UNIT_PT.get(ctx.param("unit", "cm"), UNIT_PT["cm"])
    m = {k: _num(ctx.param(k), 0) * unit for k in ("marginTop", "marginBottom", "marginLeft", "marginRight")}
    area = ctx.params.get("area") if isinstance(ctx.params.get("area"), dict) else None
    same = ctx.flag("sameForAllPages", True)
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        sel = set(pages_or_error(ctx.param("pages"), len(pdf.pages)))
        boxes = {}
        if mode == "auto":
            with pdfium_doc(inp) as doc:
                for i in range(len(pdf.pages)):
                    if i + 1 in sel:
                        boxes[i] = _content_bbox(doc, i)
            if same:
                found = [b for b in boxes.values() if b]
                if found:
                    union = (min(b[0] for b in found), min(b[1] for b in found), max(b[2] for b in found), max(b[3] for b in found))
                    boxes = {i: union for i in boxes}
        for i, page in enumerate(pdf.pages):
            if i + 1 not in sel:
                continue
            w, h = visible_size(page)
            if mode == "auto":
                b = boxes.get(i)
                if not b:
                    continue
                vx0, vy0, vx1, vy1 = b
            elif mode == "area" and area:
                ax, ay = _num(area.get("x")), _num(area.get("y"))
                vx0, vx1 = ax, ax + _num(area.get("width"))
                vy1, vy0 = h - ay, h - ay - _num(area.get("height"))
            else:
                vx0, vy0, vx1, vy1 = m["marginLeft"], m["marginBottom"], w - m["marginRight"], h - m["marginTop"]
            vx0, vy0, vx1, vy1 = max(0, vx0), max(0, vy0), min(w, vx1), min(h, vy1)
            if vx1 - vx0 < 10 or vy1 - vy0 < 10:
                raise TaskError("The crop leaves nothing of the page. Use smaller margins.")
            set_visible_crop(page, vx0, vy0, vx1, vy1)
            page.obj.MediaBox = page.obj.CropBox
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Pages cropped")


register(Tool(
    type="crop", slug="crop-pdf", title="Crop PDF", icon="crop", category="pages",
    tagline="Trim white margins automatically, or cut pages to the area or margins you choose.",
    handler=crop, page_ui="crop", keywords="trim margins cut whitespace",
    options=[
        Opt("cropMode", "How to crop", "radio", [("auto", "Trim white margins"), ("margins", "Set margins"), ("area", "Draw an area")], "auto"),
        Opt("sameForAllPages", "Use the same crop for every page", "checkbox", default=True, show_if={"cropMode": "auto"}),
        Opt("unit", "Unit", "radio", [("cm", "cm"), ("inch", "inch"), ("mm", "mm")], "cm", show_if={"cropMode": "margins"}),
        Opt("marginTop", "Top", "number", default=1, min=0, step=0.1, show_if={"cropMode": "margins"}),
        Opt("marginBottom", "Bottom", "number", default=1, min=0, step=0.1, show_if={"cropMode": "margins"}),
        Opt("marginLeft", "Left", "number", default=1, min=0, step=0.1, show_if={"cropMode": "margins"}),
        Opt("marginRight", "Right", "number", default=1, min=0, step=0.1, show_if={"cropMode": "margins"}),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# resize


def resize(ctx):
    size = (ctx.param("pageSize") or "a4").lower()
    unit = UNIT_PT.get(ctx.param("unit", "cm"), UNIT_PT["cm"])
    m = {k: _num(ctx.param(k), 0) * unit for k in ("marginTop", "marginBottom", "marginLeft", "marginRight")}
    for inp in ctx.inputs:
        src = open_pdf(inp)
        sel = set(pages_or_error(ctx.param("pages"), len(src.pages)))
        dst = pikepdf.new()
        for i, page in enumerate(src.pages):
            ctx.check_cancelled()
            dst.pages.append(page)
            if i + 1 not in sel:
                continue
            sp = dst.pages[-1]
            w, h = visible_size(sp)
            if size == "original":
                tw, th = w + m["marginLeft"] + m["marginRight"], h + m["marginTop"] + m["marginBottom"]
            elif size == "custom":
                tw, th = _num(ctx.param("pageSizeWidth"), 0) * unit, _num(ctx.param("pageSizeHeight"), 0) * unit
                if tw < 36 or th < 36:
                    raise TaskError("Enter a custom page width and height")
            else:
                tw, th = PAGE_SIZES_PT.get(size, PAGE_SIZES_PT["a4"])
                if (w > h) != (tw > th):
                    tw, th = th, tw
            new = new_blank_page(dst, tw, th, index=len(dst.pages) - 1)
            rect = (m["marginLeft"], m["marginBottom"], tw - m["marginLeft"] - m["marginRight"], th - m["marginTop"] - m["marginBottom"])
            if rect[2] <= 10 or rect[3] <= 10:
                raise TaskError("The margins are larger than the page")
            place_page(dst, new, dst.pages[-1], rect)
            del dst.pages[-1]
        save_pdf(dst, ctx.output(output_name(ctx, inp)))
    ctx.remark("Pages resized")


register(Tool(
    type="resizePages", slug="resize-pdf", title="Resize PDF", icon="resize", category="pages",
    tagline="Change the paper size of pages, or add margins around the content.",
    handler=resize, keywords="page size a4 letter margins padding scale",
    options=[
        Opt("pageSize", "New page size", "select", [("a4", "A4"), ("letter", "Letter"), ("legal", "Legal"), ("a3", "A3"), ("a5", "A5"),
            ("a6", "A6"), ("a2", "A2"), ("a1", "A1"), ("tabloid", "Tabloid"), ("ledger", "Ledger"), ("executive", "Executive"),
            ("original", "Keep size, add margins"), ("custom", "Custom")], "a4"),
        Opt("unit", "Unit", "radio", [("cm", "cm"), ("inch", "inch"), ("mm", "mm")], "cm"),
        Opt("pageSizeWidth", "Width", "number", min=1, step=0.1, show_if={"pageSize": "custom"}),
        Opt("pageSizeHeight", "Height", "number", min=1, step=0.1, show_if={"pageSize": "custom"}),
        Opt("marginTop", "Top margin", "number", default=0, min=0, step=0.1, advanced=True),
        Opt("marginBottom", "Bottom margin", "number", default=0, min=0, step=0.1, advanced=True),
        Opt("marginLeft", "Left margin", "number", default=0, min=0, step=0.1, advanced=True),
        Opt("marginRight", "Right margin", "number", default=0, min=0, step=0.1, advanced=True),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# n-up

_GRID = {2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 16: (4, 4), 32: (8, 4)}


def nup(ctx):
    n = int(_num(ctx.param("n"), 2))
    if n not in _GRID:
        raise TaskError("Choose 2, 4, 8, 16 or 32 pages per sheet")
    vertical = ctx.param("pageOrdering", "horizontal") == "vertical"
    preserve = ctx.flag("preservePageSize")
    rtl = ctx.flag("rightToLeft")
    for inp in ctx.inputs:
        src = open_pdf(inp)
        if not len(src.pages):
            continue
        dst = pikepdf.new()
        pw, ph = visible_size(src.pages[0])
        cols, rows = _GRID[n]
        if pw > ph:  # landscape pages: stack more rows than columns
            cols, rows = rows, cols
        if preserve:
            sw, sh = pw, ph
            if (cols * pw > rows * ph) != (sw > sh):
                sw, sh = sh, sw
        else:
            sw, sh = cols * pw, rows * ph
        cw, ch = sw / cols, sh / rows
        for i in range(len(src.pages)):
            dst.pages.append(src.pages[i])
        count = len(dst.pages)
        for start in range(0, count, n):
            sheet = new_blank_page(dst, sw, sh)
            for k in range(min(n, count - start)):
                r, c = (k % rows, k // rows) if vertical else (k // cols, k % cols)
                if rtl:
                    c = cols - 1 - c
                place_page(dst, sheet, dst.pages[start + k], (c * cw, sh - (r + 1) * ch, cw, ch))
        for _ in range(count):
            del dst.pages[0]
        save_pdf(dst, ctx.output(output_name(ctx, inp)))
    ctx.remark(f"Placed {n} pages on each sheet")


register(Tool(
    type="nup", slug="n-up-pdf", title="N-up pages", icon="nup", category="pages",
    tagline="Print several pages on one sheet: 2, 4, 8, 16 or 32 pages per side.",
    handler=nup, keywords="pages per sheet imposition booklet print handout",
    options=[
        Opt("n", "Pages per sheet", "radio", [("2", "2"), ("4", "4"), ("8", "8"), ("16", "16"), ("32", "32")], "2"),
        Opt("pageOrdering", "Order", "radio", [("horizontal", "Across, then down"), ("vertical", "Down, then across")], "horizontal", advanced=True),
        Opt("preservePageSize", "Keep the original page size (shrink pages to fit)", "checkbox", advanced=True),
        Opt("rightToLeft", "Right to left", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# flip


def flip(ctx):
    horizontal = ctx.param("flipMode", "horizontal") == "horizontal"
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        sel = set(pages_or_error(ctx.param("pages"), len(pdf.pages)))
        for i, page in enumerate(pdf.pages):
            if i + 1 not in sel:
                continue
            w, h = visible_size(page)
            vis = (-1, 0, 0, 1, w, 0) if horizontal else (1, 0, 0, -1, 0, h)
            u2v = user_to_visible(page)
            m = mul(mul(u2v, vis), invert(u2v))  # flip in displayed space, expressed in user space
            page.contents_add(pikepdf.Stream(pdf, f"q {_fmt(m)} cm\n".encode()), prepend=True)
            page.contents_add(pikepdf.Stream(pdf, b"\nQ\n"))
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Pages mirrored")


register(Tool(
    type="flip", slug="flip-pdf", title="Flip PDF", icon="flip", category="pages",
    tagline="Mirror pages horizontally or vertically, e.g. for iron-on transfers or reversed scans.",
    handler=flip, keywords="mirror reverse",
    options=[
        Opt("flipMode", "Direction", "radio", [("horizontal", "Horizontally (left ↔ right)"), ("vertical", "Vertically (top ↕ bottom)")], "horizontal"),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# grayscale

_COLOR_OPS = {"rg", "RG", "k", "K", "sc", "SC", "scn", "SCN", "cs", "CS"}


def _lum(vals):
    if len(vals) == 3:
        r, g, b = vals
        return 0.299 * r + 0.587 * g + 0.114 * b
    if len(vals) == 4:
        c, m, y, k = vals
        return max(0.0, 1 - min(1.0, 0.299 * c + 0.587 * m + 0.114 * y + k))
    return vals[0] if vals else 0


def _gray_stream(pdf, data_owner, resources, text_black: bool, depth=0):
    """Rewrite colour operators of one content stream (or form) into gray."""
    try:
        ops = pikepdf.parse_content_stream(data_owner)
    except Exception:
        return
    cs_names = resources.get("/ColorSpace", {}) if resources is not None else {}

    def comps(name):
        if name in ("/DeviceRGB", "/CalRGB"):
            return 3
        if name in ("/DeviceCMYK",):
            return 4
        if name in ("/DeviceGray", "/CalGray"):
            return 1
        try:
            cs = cs_names.get(name)
            if isinstance(cs, pikepdf.Array) and str(cs[0]) == "/ICCBased":
                return int(cs[1].get("/N", 3))
            if isinstance(cs, pikepdf.Array) and str(cs[0]) in ("/CalRGB", "/Lab"):
                return 3
        except Exception:
            pass
        return 0  # pattern, separation, indexed …: leave alone

    out, in_text = [], False
    stroke_comps = fill_comps = 1
    for operands, op in ops:
        o = str(op)
        if o == "BT":
            in_text = True
        elif o == "ET":
            in_text = False
        if o in ("rg", "RG", "k", "K"):
            g = _lum([float(x) for x in operands])
            if text_black and in_text:
                g = 0
            out.append(([g], pikepdf.Operator("g" if o in ("rg", "k") else "G")))
            continue
        if o in ("cs", "CS"):
            n = comps(str(operands[0]))
            if o == "cs":
                fill_comps = n
            else:
                stroke_comps = n
            if n in (3, 4, 1):
                out.append(([Name.DeviceGray], op))
                continue
        if o in ("sc", "scn", "SC", "SCN"):
            n = fill_comps if o in ("sc", "scn") else stroke_comps
            nums = [x for x in operands if isinstance(x, (int, float, pikepdf.Object)) and not isinstance(x, pikepdf.Name)]
            if n in (3, 4) and len(nums) == n:
                g = _lum([float(x) for x in nums])
                if text_black and in_text:
                    g = 0
                out.append(([g], op))
                continue
        if o in ("g", "G") and text_black and in_text:
            out.append(([0], op))
            continue
        if o == "Do" and depth < 6 and resources is not None:
            xo = resources.get("/XObject", {}).get(str(operands[0])) if "/XObject" in resources else None
            if isinstance(xo, pikepdf.Stream) and xo.get("/Subtype") == Name.Form:
                _gray_stream(pdf, xo, xo.get("/Resources", resources), text_black, depth + 1)
        out.append((operands, op))
    data = pikepdf.unparse_content_stream(out)
    if isinstance(data_owner, pikepdf.Page):
        data_owner.obj.Contents = pikepdf.Stream(pdf, data)
    else:
        data_owner.write(data)


def grayscale(ctx):
    text_black = ctx.param("textConversion", "grayscale") == "black"
    convert_images = ctx.param("imageConversion", "grayscale") != "none"
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        for page in pdf.pages:
            ctx.check_cancelled()
            _gray_stream(pdf, page, page.obj.get("/Resources"), text_black)
        if convert_images:
            for xo, display in iter_image_xobjects(pdf):
                recompress_image(xo, 85, 300 if ctx.flag("compressImages") else None, display, True)
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Converted to grayscale")


register(Tool(
    type="grayscale", slug="grayscale-pdf", title="Grayscale PDF", icon="grayscale", category="optimize",
    tagline="Turn text, drawings and images black-and-white, ready for cheaper printing.",
    handler=grayscale, keywords="black white monochrome print",
    options=[
        Opt("textConversion", "Text", "radio", [("grayscale", "Shades of gray"), ("black", "Pure black")], "grayscale"),
        Opt("imageConversion", "Images", "radio", [("grayscale", "Grayscale"), ("none", "Keep colors")], "grayscale"),
        Opt("compressImages", "Also compress images", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# deskew


def estimate_skew(doc, index: int) -> float:
    """Angle in degrees (counter-clockwise) that straightens the page, by projection-profile search."""
    import numpy as np
    from PIL import Image

    page = doc[index]
    w, h = page.get_size()
    scale = min(1.5, 1100 / max(w, h))
    img = page.render(scale=scale, grayscale=True).to_pil().convert("L")
    small = Image.eval(img, lambda v: 255 - v)  # ink = bright
    if np.asarray(small).mean() < 0.5:
        return 0.0

    def score(a):
        arr = np.asarray(small.rotate(a, resample=Image.BILINEAR, expand=False), dtype=np.float32)
        prof = arr.sum(axis=1)
        return float(np.var(prof))

    best = max((score(a), a) for a in np.arange(-10, 10.01, 0.5))[1]
    best = max((score(a), a) for a in np.arange(best - 0.5, best + 0.51, 0.1))[1]
    return round(float(best), 2)


def deskew(ctx):
    only_strong = ctx.flag("onlyStronglySkewed")
    manual = ctx.params.get("angles") if isinstance(ctx.params.get("angles"), dict) else {}
    fixed = 0
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        sel = set(pages_or_error(ctx.param("pages"), len(pdf.pages)))
        with pdfium_doc(inp) as doc:
            for i, page in enumerate(pdf.pages):
                ctx.check_cancelled()
                if i + 1 not in sel:
                    continue
                angle = _num(manual.get(str(i + 1)), None) if str(i + 1) in manual else estimate_skew(doc, i)
                if angle is None or abs(angle) < (1.0 if only_strong else 0.15):
                    continue
                x0, y0, x1, y1 = page_box(page)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                t = math.radians(angle)
                rot = (math.cos(t), math.sin(t), -math.sin(t), math.cos(t), 0, 0)
                m = mul(mul((1, 0, 0, 1, -cx, -cy), rot), (1, 0, 0, 1, cx, cy))
                page.contents_add(pikepdf.Stream(pdf, f"q {_fmt(m)} cm\n".encode()), prepend=True)
                page.contents_add(pikepdf.Stream(pdf, b"\nQ\n"))
                fixed += 1
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark(f"Straightened {fixed} page{'s' if fixed != 1 else ''}" if fixed else "No skewed pages found")


register(Tool(
    type="deskew", slug="deskew-pdf", title="Deskew PDF", icon="deskew", category="optimize",
    tagline="Automatically straighten crooked scanned pages.",
    handler=deskew, keywords="straighten scan crooked tilted",
    options=[
        Opt("onlyStronglySkewed", "Only fix pages that are clearly crooked (more than 1°)", "checkbox"),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# flatten


def flatten(ctx):
    mode = ctx.param("flattenMode", "all")
    dpi = int(_num(ctx.param("resolution"), 150) or 150)
    for inp in ctx.inputs:
        if mode == "all":
            _rasterize(ctx, inp, dpi)
            continue
        pdf = open_pdf(inp)
        try:
            pdf.generate_appearance_streams()
        except Exception:
            pass
        stash = {}
        for i, page in enumerate(pdf.pages):  # keep non-form annotations out of the flattening
            annots = page.obj.get("/Annots")
            if isinstance(annots, pikepdf.Array):
                stash[i] = [a for a in annots if a.get("/Subtype") != Name.Widget]
                page.obj.Annots = pikepdf.Array([a for a in annots if a.get("/Subtype") == Name.Widget])
        pdf.flatten_annotations("all")
        for i, keep in stash.items():
            pdf.pages[i].obj.Annots = pikepdf.Array(keep)
        if "/AcroForm" in pdf.Root:
            del pdf.Root["/AcroForm"]
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Flattened")


def _rasterize(ctx, inp, dpi: int):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = None
    with pdfium_doc(inp) as doc:
        for i in range(len(doc)):
            ctx.check_cancelled()
            page = doc[i]
            w, h = page.get_size()
            pil = page.render(scale=dpi / 72, may_draw_forms=True, draw_annots=True).to_pil().convert("RGB")
            if c is None:
                c = rl_canvas.Canvas(buf, pagesize=(w, h))
            else:
                c.setPageSize((w, h))
            img = io.BytesIO()
            pil.save(img, "JPEG", quality=88)
            img.seek(0)
            c.drawImage(ImageReader(img), 0, 0, w, h)
            c.showPage()
    if c is None:
        raise TaskError(f"'{inp.name}' has no pages")
    c.save()
    ctx.output(output_name(ctx, inp)).write_bytes(buf.getvalue())


register(Tool(
    type="flatten", slug="flatten-pdf", title="Flatten PDF", icon="flatten", category="optimize",
    tagline="Lock in form fields and annotations, or turn pages into images so text can't be edited or copied.",
    handler=flatten, keywords="lock forms read only image print",
    options=[
        Opt("flattenMode", "What to flatten", "radio", [("onlyforms", "Only form fields"), ("all", "Everything (pages become images)")], "onlyforms"),
        Opt("resolution", "Image resolution", "radio", [("75", "75 dpi"), ("100", "100 dpi"), ("150", "150 dpi"), ("220", "220 dpi")], "150",
            show_if={"flattenMode": "all"}),
    ],
))


# ---------------------------------------------------------------------------
# repair


def repair(ctx):
    for inp in ctx.inputs:
        out = ctx.output(output_name(ctx, inp))
        try:
            with pikepdf.open(inp.path, password=inp.password or "", attempt_recovery=True) as pdf:
                pages = len(pdf.pages)
                save_pdf(pdf, out)
            ctx.remark(f"Rebuilt the file structure ({pages} pages recovered)")
            continue
        except pikepdf.PasswordError:
            raise TaskError(f"'{inp.name}' is password protected. Enter its password and try again.") from None
        except Exception:
            pass
        try:
            import pypdf

            reader = pypdf.PdfReader(str(inp.path), strict=False)
            if reader.is_encrypted:
                reader.decrypt(inp.password or "")
            writer = pypdf.PdfWriter()
            recovered = 0
            for p in reader.pages:
                try:
                    writer.add_page(p)
                    recovered += 1
                except Exception:
                    continue
            if not recovered:
                raise ValueError("no pages")
            with open(out, "wb") as fh:
                writer.write(fh)
            ctx.remark(f"Recovered {recovered} page{'s' if recovered != 1 else ''}")
        except Exception:
            raise TaskError(f"'{inp.name}' is too damaged to repair") from None


register(Tool(
    type="repair", slug="repair-pdf", title="Repair PDF", icon="repair", category="optimize",
    tagline="Recover what can be saved from a damaged or corrupted PDF.",
    handler=repair, keywords="fix broken corrupt damaged recover",
))
