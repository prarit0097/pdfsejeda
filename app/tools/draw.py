"""Page geometry and drawing onto existing pages.

Two building blocks used by many tools:

* `stamp(pdf, page, w, h, draw)` — draws with reportlab on a canvas the size of
  the page *as displayed* (after /Rotate), origin bottom-left, and merges it
  onto the page. Watermarks, page numbers, Bates, the editor's operations all
  use this, so they work on rotated pages too.
* `place_page(dst_page, src_page, rect)` — draws a whole page (as a Form
  XObject) scaled into a rectangle of another page. Used by n-up, resize,
  normalize sizes, split down the middle.

Matrices are PDF style [a b c d e f]: x' = a*x + c*y + e, y' = b*x + d*y + f.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pikepdf
from pikepdf import Name

from .common import page_box, rotation

Matrix = tuple[float, float, float, float, float, float]


def mul(m1: Matrix, m2: Matrix) -> Matrix:
    """Apply m1 then m2."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def invert(m: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def visible_size(page: pikepdf.Page) -> tuple[float, float]:
    x0, y0, x1, y1 = page_box(page)
    w, h = x1 - x0, y1 - y0
    return (h, w) if rotation(page) in (90, 270) else (w, h)


def user_to_visible(page: pikepdf.Page) -> Matrix:
    """Maps the page's user space to displayed space (origin bottom-left of what the viewer shows)."""
    x0, y0, x1, y1 = page_box(page)
    r = rotation(page)
    if r == 90:
        return (0, -1, 1, 0, -y0, x1)
    if r == 180:
        return (-1, 0, 0, -1, x1, y1)
    if r == 270:
        return (0, 1, -1, 0, y1, -x0)
    return (1, 0, 0, 1, -x0, -y0)


def _fmt(m: Matrix) -> str:
    return " ".join(f"{v:.6f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v)) for v in m)


def _wrap_and_append(pdf: pikepdf.Pdf, page: pikepdf.Page, ops: bytes) -> None:
    page.contents_add(pikepdf.Stream(pdf, b"q\n"), prepend=True)
    page.contents_add(pikepdf.Stream(pdf, b"\nQ\n" + ops), prepend=False)


def draw_form(pdf: pikepdf.Pdf, page: pikepdf.Page, form: pikepdf.Object, m: Matrix, under: bool = False) -> None:
    """Paint a Form XObject on `page` with matrix `m` (form space -> page user space)."""
    name = page.add_resource(form, Name.XObject, prefix="Fx")
    ops = f"q {_fmt(m)} cm {name} Do Q\n".encode()
    if under:
        page.contents_add(pikepdf.Stream(pdf, ops), prepend=True)
    else:
        _wrap_and_append(pdf, page, ops)


def stamp(pdf: pikepdf.Pdf, page: pikepdf.Page, draw: Callable, under: bool = False) -> None:
    """Draw with reportlab in displayed coordinates and merge onto `page`.

    `draw(canvas, width, height)` receives a reportlab canvas.
    """
    from reportlab.pdfgen import canvas as rl_canvas

    w, h = visible_size(page)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    draw(c, w, h)
    c.showPage()
    c.save()
    with pikepdf.open(io.BytesIO(buf.getvalue())) as ov:
        ov_page = pdf.copy_foreign(ov.pages[0].obj)
        form = pikepdf.Page(ov_page).as_form_xobject()
    draw_form(pdf, page, form, invert(user_to_visible(page)), under=under)


def page_form(pdf: pikepdf.Pdf, src: pikepdf.Page) -> pikepdf.Object:
    """Form XObject of `src` (which must belong to `pdf`), clipped to its visible box."""
    form = src.as_form_xobject()
    x0, y0, x1, y1 = page_box(src)
    form.BBox = pikepdf.Array([x0, y0, x1, y1])
    return form


def place_page(pdf: pikepdf.Pdf, dst: pikepdf.Page, src: pikepdf.Page, rect: tuple[float, float, float, float],
               keep_ratio: bool = True, extra_rotation: int = 0) -> None:
    """Draw `src` (displayed orientation, plus `extra_rotation` CW degrees) scaled into rect=(x, y, w, h) of `dst`."""
    x, y, rw, rh = rect
    m = user_to_visible(src)
    vw, vh = visible_size(src)
    r = extra_rotation % 360
    if r == 90:
        m, vw, vh = mul(m, (0, -1, 1, 0, 0, vw)), vh, vw
    elif r == 180:
        m = mul(m, (-1, 0, 0, -1, vw, vh))
    elif r == 270:
        m, vw, vh = mul(m, (0, 1, -1, 0, vh, 0)), vh, vw
    sx, sy = rw / vw, rh / vh
    if keep_ratio:
        sx = sy = min(sx, sy)
    ox = x + (rw - vw * sx) / 2
    oy = y + (rh - vh * sy) / 2
    m = mul(m, (sx, 0, 0, sy, ox, oy))
    draw_form(pdf, dst, page_form(pdf, src), m)


def new_blank_page(pdf: pikepdf.Pdf, w: float, h: float, index: int | None = None) -> pikepdf.Page:
    page = pikepdf.Dictionary(Type=Name.Page, MediaBox=[0, 0, w, h], Resources=pikepdf.Dictionary(),
                              Contents=pikepdf.Stream(pdf, b""))
    if index is None:
        pdf.pages.append(pikepdf.Page(page))
        return pdf.pages[-1]
    pdf.pages.insert(index, pikepdf.Page(page))
    return pdf.pages[index]


def hex_to_rgb(color: str | None, default=(0, 0, 0)) -> tuple[float, float, float]:
    if not color:
        return default
    c = str(color).strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


# ---- fonts ---------------------------------------------------------------

BASE14 = {
    "helvetica": "Helvetica", "times_roman": "Times-Roman", "times": "Times-Roman", "courier": "Courier",
    "times new roman": "Times-Roman", "courier new": "Courier", "arial": "Helvetica",
}

_FONT_DIRS = [Path(__file__).resolve().parent.parent / "static" / "fonts", Path("/usr/share/fonts"),
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"]
_UNICODE_CANDIDATES = ["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"]


@lru_cache(maxsize=None)
def _find_font_file(filename: str) -> str | None:
    for d in _FONT_DIRS:
        if not d.exists():
            continue
        direct = d / filename
        if direct.exists():
            return str(direct)
        for p in d.rglob(filename):
            return str(p)
    return None


@lru_cache(maxsize=None)
def unicode_font() -> str | None:
    """Register and return a TTF font name that covers most scripts, if one is installed."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for fn in _UNICODE_CANDIDATES:
        path = _find_font_file(fn)
        if path:
            try:
                pdfmetrics.registerFont(TTFont("UniSans", path))
                return "UniSans"
            except Exception:
                continue
    return None


def font_for(name: str | None, text: str = "", bold: bool = False, italic: bool = False) -> str:
    """Pick a reportlab font: base-14 when the text is Latin-1, otherwise a Unicode TTF."""
    needs_unicode = any(ord(ch) > 255 for ch in text)
    if needs_unicode:
        uni = unicode_font()
        if uni:
            return uni
    base = BASE14.get((name or "helvetica").lower().strip(), None)
    if base is None:
        n = (name or "").lower()
        if "mono" in n or "courier" in n:
            base = "Courier"
        elif "times" in n or ("serif" in n and "sans" not in n):
            base = "Times-Roman"
        else:
            base = "Helvetica"
    variants = {
        "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
        "Times-Roman": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
        "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
    }[base]
    return variants[(1 if bold else 0) + (2 if italic else 0)]
