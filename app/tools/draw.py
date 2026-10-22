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
    # handle_transformations=False: callers apply /Rotate themselves via user_to_visible(); letting
    # pikepdf bake it into the form's /Matrix as well would rotate rotated pages twice.
    form = src.as_form_xobject(handle_transformations=False)
    if "/Matrix" in form:
        del form["/Matrix"]
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


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def transform_annotations(page: pikepdf.Page, m: Matrix) -> None:
    """Move/scale/mirror the page's annotations (and their geometry keys) with user-space matrix `m`,
    so links, comments and form fields stay on the content they belong to."""
    annots = page.obj.get("/Annots")
    if not isinstance(annots, pikepdf.Array):
        return
    for a in annots:
        try:
            if not isinstance(a, pikepdf.Dictionary):
                continue
            rect = a.get("/Rect")
            if isinstance(rect, pikepdf.Array) and len(rect) == 4:
                x0, y0, x1, y1 = (float(v) for v in rect)
                pts = [_apply(m, x, y) for x, y in ((x0, y0), (x1, y1), (x0, y1), (x1, y0))]
                a.Rect = pikepdf.Array([min(p[0] for p in pts), min(p[1] for p in pts),
                                        max(p[0] for p in pts), max(p[1] for p in pts)])
            for key in ("/QuadPoints", "/L", "/Vertices", "/CL"):
                arr = a.get(key)
                if isinstance(arr, pikepdf.Array) and len(arr) % 2 == 0:
                    vals = [float(v) for v in arr]
                    out = []
                    for i in range(0, len(vals), 2):
                        out.extend(_apply(m, vals[i], vals[i + 1]))
                    a[key] = pikepdf.Array(out)
            ink = a.get("/InkList")
            if isinstance(ink, pikepdf.Array):
                new_ink = []
                for stroke in ink:
                    vals = [float(v) for v in stroke]
                    out = []
                    for i in range(0, len(vals) - 1, 2):
                        out.extend(_apply(m, vals[i], vals[i + 1]))
                    new_ink.append(pikepdf.Array(out))
                a.InkList = pikepdf.Array(new_ink)
        except Exception:
            continue


def fit_page_content(pdf: pikepdf.Pdf, page: pikepdf.Page, rect: tuple[float, float, float, float],
                     new_size: tuple[float, float] | None = None, keep_ratio: bool = True) -> Matrix:
    """Scale the page's visible content into rect=(x, y, w, h), in displayed coordinates, *in place*.

    With `new_size=(w, h)` the page first gets that displayed size (its /Rotate is kept). Unlike
    `place_page` onto a new page, the page object survives, so bookmarks, links, comments and form
    fields keep working; annotations are moved along. Content outside the old visible box stays hidden.
    Returns the user-space matrix applied."""
    old_u2v = user_to_visible(page)
    vw, vh = visible_size(page)
    bx0, by0, bx1, by1 = page_box(page)
    if new_size:
        tw, th = new_size
        bw, bh = (th, tw) if rotation(page) in (90, 270) else (tw, th)
        page.obj.MediaBox = pikepdf.Array([0, 0, bw, bh])
        for key in ("/CropBox", "/TrimBox", "/BleedBox", "/ArtBox"):
            if key in page.obj:
                del page.obj[key]
    x, y, rw, rh = rect
    sx, sy = rw / vw, rh / vh
    if keep_ratio:
        sx = sy = min(sx, sy)
    ox, oy = x + (rw - vw * sx) / 2, y + (rh - vh * sy) / 2
    m = mul(mul(old_u2v, (sx, 0, 0, sy, ox, oy)), invert(user_to_visible(page)))
    clip = f"{_fmt((bx0, by0, bx1 - bx0, by1 - by0, 0, 0)[:4])} re W n\n"
    page.contents_add(pikepdf.Stream(pdf, f"q {_fmt(m)} cm {clip}".encode()), prepend=True)
    page.contents_add(pikepdf.Stream(pdf, b"\nQ\n"))
    transform_annotations(page, m)
    return m


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
              Path("/usr/local/share/fonts"), Path.home() / ".fonts",
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
              Path(os.environ.get("LOCALAPPDATA", "/nonexistent")) / "Microsoft" / "Windows" / "Fonts",
              Path("/System/Library/Fonts"), Path("/Library/Fonts")]
_UNICODE_CANDIDATES = ["NotoSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"]

# Fallback chain for characters the base-14 fonts can't show, in preference order. The first
# installed font whose cmap contains a character draws it. Covers Linux (Noto/DejaVu/Lohit/WenQuanYi
# packages) and Windows (Nirmala UI, Microsoft YaHei, …). Entries are (file name, subfont index).
_FALLBACK_FONTS = [
    ("NotoSans-Regular.ttf", 0), ("DejaVuSans.ttf", 0), ("arial.ttf", 0), ("LiberationSans-Regular.ttf", 0),
    ("segoeui.ttf", 0), ("Arial Unicode.ttf", 0),
    # Indic
    ("NotoSansDevanagari-Regular.ttf", 0), ("NotoSansBengali-Regular.ttf", 0), ("NotoSansTamil-Regular.ttf", 0),
    ("NotoSansTelugu-Regular.ttf", 0), ("NotoSansGujarati-Regular.ttf", 0), ("NotoSansGurmukhi-Regular.ttf", 0),
    ("NotoSansKannada-Regular.ttf", 0), ("NotoSansMalayalam-Regular.ttf", 0), ("NotoSansOriya-Regular.ttf", 0),
    ("Nirmala.ttc", 0), ("Nirmala.ttf", 0), ("mangal.ttf", 0), ("Lohit-Devanagari.ttf", 0), ("FreeSans.ttf", 0),
    # Arabic, Hebrew, Thai
    ("NotoSansArabic-Regular.ttf", 0), ("NotoNaskhArabic-Regular.ttf", 0), ("NotoSansHebrew-Regular.ttf", 0),
    ("NotoSansThai-Regular.ttf", 0), ("LeelawUI.ttf", 0), ("tahoma.ttf", 0),
    # CJK
    ("msyh.ttc", 0), ("simsun.ttc", 0), ("YuGothR.ttc", 0), ("msgothic.ttc", 0), ("malgun.ttf", 0),
    ("NotoSansCJK-Regular.ttc", 0), ("NotoSansCJKsc-Regular.otf", 0), ("NotoSansSC-Regular.otf", 0),
    ("NotoSansSC-Regular.ttf", 0), ("DroidSansFallbackFull.ttf", 0), ("wqy-zenhei.ttc", 0), ("wqy-microhei.ttc", 0),
    ("NanumGothic.ttf", 0), ("ipag.ttf", 0),
    # symbols
    ("seguisym.ttf", 0), ("NotoSansSymbols-Regular.ttf", 0), ("NotoSansSymbols2-Regular.ttf", 0),
]

# Scripts that need a shaping engine (glyph reordering / joining) to look right.
_SHAPED_RANGES = [(0x0590, 0x08FF), (0x0900, 0x0DFF), (0x0E00, 0x0EFF), (0x0F00, 0x0FFF), (0x1000, 0x109F),
                  (0x1780, 0x17FF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF)]
_RTL_RANGES = [(0x0590, 0x08FF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF)]


@lru_cache(maxsize=None)
def _font_index() -> dict:
    """lower-case file name -> path, for every font file under the font directories (scanned once)."""
    index: dict[str, str] = {}
    for d in _FONT_DIRS:
        try:
            if not d.is_dir():
                continue
            for p in d.rglob("*"):
                if p.suffix.lower() in (".ttf", ".ttc", ".otf"):
                    index.setdefault(p.name.lower(), str(p))
        except OSError:
            continue
    return index


@lru_cache(maxsize=None)
def _find_font_file(filename: str) -> str | None:
    return _font_index().get(filename.lower())


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




class _Fallback:
    """One installed fallback font: its cmap, and (if reportlab can embed it) a registered font name."""

    def __init__(self, path: str, index: int):
        from fontTools.ttLib import TTFont as FTFont

        self.path, self.index = path, index
        self.ft = FTFont(path, fontNumber=index, lazy=True)
        self.cmap = set(self.ft.getBestCmap() or {})
        self.upem = self.ft["head"].unitsPerEm
        self._rl_name: str | None = None
        self._rl_tried = False

    @property
    def rl_name(self) -> str | None:
        """reportlab font name (registered on first use), or None if reportlab can't embed this font
        (e.g. CFF-flavoured OpenType); such fonts are drawn as outlines instead."""
        if not self._rl_tried:
            self._rl_tried = True
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont

                name = "Fb-" + Path(self.path).stem.replace(" ", "") + (f"-{self.index}" if self.index else "")
                try:
                    pdfmetrics.getFont(name)
                except KeyError:
                    pdfmetrics.registerFont(TTFont(name, self.path, subfontIndex=self.index))
                self._rl_name = name
            except Exception:
                self._rl_name = None
        return self._rl_name


@lru_cache(maxsize=None)
def _fallbacks() -> tuple:
    out, seen = [], set()
    for fn, idx in _FALLBACK_FONTS:
        path = _find_font_file(fn)
        if not path or (path.lower(), idx) in seen:
            continue
        seen.add((path.lower(), idx))
        try:
            out.append(_Fallback(path, idx))
        except Exception:
            continue
    return tuple(out)


def _fallback_for(ch: str):
    cp = ord(ch)
    for fb in _fallbacks():
        if cp in fb.cmap:
            return fb
    return None


def _winansi(ch: str) -> bool:
    """True when a base-14 font (WinAnsiEncoding) can show the character."""
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _in(ranges, ch: str) -> bool:
    cp = ord(ch)
    return any(a <= cp <= b for a, b in ranges)


def font_for(name: str | None, text: str = "", bold: bool = False, italic: bool = False) -> str:
    """Pick one reportlab font for `text`: base-14 when it fits WinAnsi, otherwise the installed Unicode
    TTF that covers most of it (so Hindi/Chinese/… don't come out as empty boxes).

    For mixed-script text prefer `draw_text()`, which switches fonts per run and shapes complex scripts."""
    special = [ch for ch in text if not _winansi(ch) and not ch.isspace()]
    if special:
        best, best_n = None, 0
        for fb in _fallbacks():
            n = sum(1 for ch in special if ord(ch) in fb.cmap)
            if n > best_n and fb.rl_name:
                best, best_n = fb, n
            if best_n == len(special):
                break
        if best is not None:
            return best.rl_name
        uni = unicode_font()
        if uni:
            return uni
    return _base14(name, bold, italic)


def _base14(name: str | None, bold: bool = False, italic: bool = False) -> str:
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


# ---- mixed-script text -----------------------------------------------------


def _runs(text: str, name: str | None, bold: bool):
    """Split text into [string, font] runs, font = base-14 name or a _Fallback. Spaces and punctuation
    stay in the current run so a Hindi phrase isn't chopped at every space."""
    base = _base14(name, bold)
    runs: list[list] = []
    for ch in text:
        cur = runs[-1][1] if runs else None
        neutral = ch.isspace() or not ch.isalnum()
        if cur is not None and not isinstance(cur, str) and neutral and ord(ch) in cur.cmap:
            font = cur
        elif _winansi(ch):
            font = base
        elif cur is not None and not isinstance(cur, str) and ord(ch) in cur.cmap:
            font = cur
        else:
            font = _fallback_for(ch) or base  # nothing installed covers it: the base font shows a box
        if runs and runs[-1][1] is font:
            runs[-1][0] += ch
        else:
            runs.append([ch, font])
    return runs


@lru_cache(maxsize=None)
def _hb_font(path: str, index: int):
    """HarfBuzz font when the optional `uharfbuzz` package is installed, else None."""
    try:
        import uharfbuzz as hb
    except ImportError:
        return None
    with open(path, "rb") as fh:
        face = hb.Face(hb.Blob(fh.read()), index)
    return hb.Font(face)


def _needs_outline(run: str, fb) -> bool:
    if fb.rl_name is None:
        return True
    return any(_in(_SHAPED_RANGES, ch) for ch in run) and _hb_font(fb.path, fb.index) is not None


@lru_cache(maxsize=512)
def _glyphs(run: str, fb) -> tuple:
    """((glyph name, x_offset, y_offset, advance), …) in font units, shaped with HarfBuzz when available."""
    order = fb.ft.getGlyphOrder()
    hbf = _hb_font(fb.path, fb.index)
    if hbf is not None:
        import uharfbuzz as hb

        buf = hb.Buffer()
        buf.add_str(run)
        buf.guess_segment_properties()
        hb.shape(hbf, buf, {})
        k = fb.upem / (hbf.scale[0] or fb.upem)
        return tuple((order[i.codepoint] if i.codepoint < len(order) else ".notdef", p.x_offset * k, p.y_offset * k,
                      p.x_advance * k) for i, p in zip(buf.glyph_infos, buf.glyph_positions))
    cmap = fb.ft.getBestCmap() or {}
    hmtx = fb.ft["hmtx"]
    out = []
    for ch in run:
        g = cmap.get(ord(ch), ".notdef")
        out.append((g, 0, 0, hmtx[g][0] if g in hmtx.metrics else 0))
    return tuple(out)


def _run_width(run: str, font, size: float) -> float:
    from reportlab.pdfbase import pdfmetrics

    if isinstance(font, str):
        return pdfmetrics.stringWidth(run, font, size)
    if _needs_outline(run, font):
        return sum(g[3] for g in _glyphs(run, font)) * size / font.upem
    return pdfmetrics.stringWidth(run, font.rl_name, size)


def _ordered_runs(text: str, name: str | None, bold: bool):
    runs = _runs(text, name, bold)
    first_strong = next((ch for ch in text if ch.isalpha()), "")
    if first_strong and _in(_RTL_RANGES, first_strong):
        runs.reverse()  # right-to-left paragraph: runs are laid out right to left
    return runs


def text_width(text: str, name: str | None, size: float, bold: bool = False) -> float:
    """Width in points of `text` as `draw_text` draws it."""
    return sum(_run_width(r, f, size) for r, f in _ordered_runs(text, name, bold))


def draw_text(c, x: float, y: float, text: str, name: str | None, size: float, align: str = "left",
              bold: bool = False) -> float:
    """Draw one line on a reportlab canvas with per-run font fallback: base-14 for WinAnsi text, installed
    Unicode fonts for the rest. Complex scripts (Indic, Arabic, …) are shaped with HarfBuzz and drawn as
    outlines when the optional `uharfbuzz` package is installed. Uses the canvas' current fill colour
    and alpha. `align` is left|center|right relative to x. Returns the width drawn."""
    runs = _ordered_runs(text, name, bold)
    widths = [_run_width(r, f, size) for r, f in runs]
    total = sum(widths)
    cx = x - (total / 2 if align == "center" else total if align == "right" else 0)
    for (run, font), w in zip(runs, widths):
        if isinstance(font, str) or not _needs_outline(run, font):
            c.setFont(font if isinstance(font, str) else font.rl_name, size)
            c.drawString(cx, y, run)
        else:
            _draw_outlines(c, cx, y, run, font, size, bold)
        cx += w
    return total


def _draw_outlines(c, x: float, y: float, run: str, fb, size: float, bold: bool) -> None:
    from fontTools.pens.basePen import BasePen

    k = size / fb.upem
    path = c.beginPath()

    class Pen(BasePen):
        def __init__(self, glyphset, ox, oy):
            super().__init__(glyphset)
            self.ox, self.oy = ox, oy

        def _pt(self, p):
            return self.ox + p[0] * k, self.oy + p[1] * k

        def _moveTo(self, p):
            path.moveTo(*self._pt(p))

        def _lineTo(self, p):
            path.lineTo(*self._pt(p))

        def _curveToOne(self, p1, p2, p3):
            path.curveTo(*self._pt(p1), *self._pt(p2), *self._pt(p3))

        def _qCurveToOne(self, p1, p2):
            p0 = self._getCurrentPoint()
            c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
            c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
            path.curveTo(*self._pt(c1), *self._pt(c2), *self._pt(p2))

        def _closePath(self):
            path.close()

    glyphset = fb.ft.getGlyphSet()
    pen_x = 0.0
    for gname, dx, dy, adv in _glyphs(run, fb):
        if gname in glyphset:
            glyphset[gname].draw(Pen(glyphset, x + (pen_x + dx) * k, y + dy * k))
        pen_x += adv
    c.saveState()
    if bold:  # fake bold: stroke the outline in the fill colour
        c.setLineWidth(size * 0.03)
        c.setStrokeColor(c._fillColorObj)
    c.drawPath(path, stroke=1 if bold else 0, fill=1, fillMode=1)
    c.restoreState()
