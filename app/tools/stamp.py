"""Stamp & number tools: watermark, header/footer (and page numbers), Bates numbering."""
from __future__ import annotations

import math
import time

import pikepdf

from ..jobs import TaskError
from .common import open_pdf, output_name, pages_or_error, save_pdf
from .draw import draw_text, fit_page_content, hex_to_rgb, stamp, text_width, visible_size
from .imaging import is_image
from .registry import IMAGES, PDF, Opt, Tool, register

LOCATIONS = [("top-left", "Top left"), ("top-center", "Top center"), ("top-right", "Top right"),
             ("bottom-left", "Bottom left"), ("bottom-center", "Bottom center"), ("bottom-right", "Bottom right")]
FONTS = [("helvetica", "Sans-serif"), ("times_roman", "Serif"), ("courier", "Monospace")]
SIZES = [(str(s), str(s)) for s in (6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 22, 24, 26, 28, 30, 36, 45, 60)]


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default: int) -> int:
    """Integer option where 0 is a valid value (unlike `int(x or default)`)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def roman(n: int) -> str:
    if n <= 0:
        return str(n)
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _label_margin(size: float) -> float:
    return max(18, size * 1.6)


def _label_room(text: str, size: float) -> float:
    """Height of the band a label needs (margin + its lines), used by "add margins"."""
    lines = max(1, len(text.split("\n")))
    return _label_margin(size) + size * 0.8 + (lines - 1) * size * 1.2 + size * 0.6


def _draw_label(c, w, h, text, location, font, size, color, margin=None):
    lines = text.split("\n")
    margin = margin if margin is not None else _label_margin(size)
    c.setFillColorRGB(*color)
    lead = size * 1.2
    vert, horiz = location.split("-")
    for i, line in enumerate(lines):
        y = (h - margin - size * 0.8 - i * lead) if vert == "top" else (margin + (len(lines) - 1 - i) * lead)
        if horiz == "left":
            draw_text(c, margin, y, line, font, size, "left")
        elif horiz == "right":
            draw_text(c, w - margin, y, line, font, size, "right")
        else:
            draw_text(c, w / 2, y, line, font, size, "center")


def _shrink_for_margin(pdf, idx: int, location: str, room: float):
    """Scale page content down in place (links, bookmarks and form fields keep working) so a
    header/footer band of height `room` doesn't cover it."""
    page = pdf.pages[idx]
    w, h = visible_size(page)
    room = min(room, h * 0.4)
    y = room if location.startswith("bottom") else 0
    fit_page_content(pdf, page, (0, y, w, h - room))


# ---------------------------------------------------------------------------
# header / footer + page numbers


def header_footer(ctx):
    pattern = (ctx.param("pattern") or "").strip() or "Page [PAGE_ARABIC] of [TOTAL_PAGES_ARABIC]"
    location = ctx.param("pageLocation", "bottom-center")
    if location not in dict(LOCATIONS):
        location = "bottom-center"
    font = ctx.param("font", "helvetica")
    size = _num(ctx.param("fontSize"), 10) or 10
    color = hex_to_rgb(ctx.param("color"))
    start_from = _int(ctx.param("pageCountStartFrom"), 1)
    add_margins = ctx.flag("addMargins")
    date = time.strftime("%Y-%m-%d")
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        total = len(pdf.pages)
        sel = pages_or_error(ctx.param("pages"), total)
        total_numbered = start_from + total - 1
        for i in sel:
            ctx.check_cancelled()
            idx = i - 1
            n = start_from + idx
            text = (pattern.replace("[PAGE_ARABIC]", str(n)).replace("[PAGE_ROMAN_UPPER]", roman(n).upper())
                    .replace("[PAGE_ROMAN]", roman(n)).replace("[TOTAL_PAGES_ARABIC]", str(total_numbered))
                    .replace("[TOTAL_PAGES_ROMAN]", roman(total_numbered)).replace("[BASE_NAME]", inp.stem)
                    .replace("[FILE_NAME]", inp.name).replace("[DATE]", date))
            if add_margins:
                _shrink_for_margin(pdf, idx, location, _label_room(text, size))
            stamp(pdf, pdf.pages[idx], lambda c, w, h, t=text: _draw_label(c, w, h, t, location, font, size, color))
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Header and footer added")


_HF_OPTS = lambda default_pattern: [  # noqa: E731
    Opt("pattern", "Text", "text", default=default_pattern,
        help="Tokens: [PAGE_ARABIC] [PAGE_ROMAN] [TOTAL_PAGES_ARABIC] [BASE_NAME] [FILE_NAME] [DATE]"),
    Opt("pageLocation", "Position", "select", LOCATIONS, "bottom-center"),
    Opt("fontSize", "Font size", "select", SIZES, "10"),
    Opt("font", "Font", "radio", FONTS, "helvetica", advanced=True),
    Opt("color", "Color", "color", default="#000000", advanced=True),
    Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    Opt("pageCountStartFrom", "First page number", "number", default=1, min=0, advanced=True),
    Opt("addMargins", "Shrink pages so the text doesn't overlap content", "checkbox", advanced=True),
]

register(Tool(
    type="headerFooter", slug="header-footer-pdf", title="Header & footer", icon="header", category="stamp",
    tagline="Add text such as a title, date or page numbers to the top or bottom of pages.",
    handler=header_footer, keywords="header footer text label date",
    options=_HF_OPTS("[BASE_NAME] — page [PAGE_ARABIC]"),
))


def _page_numbers(ctx):
    return header_footer(ctx)


register(Tool(
    type="pageNumbers", slug="page-numbers-pdf", title="Add page numbers", icon="number", category="stamp", popular=True,
    tagline="Number the pages of a PDF, with the position, style and starting number you choose.",
    handler=_page_numbers, keywords="paginate numbering page numbers",
    options=_HF_OPTS("[PAGE_ARABIC]"),
))


# ---------------------------------------------------------------------------
# Bates numbering

BATES_STYLES = [
    ("full", "Case XYZ 000001", "[CASE] [BATES_NUMBER]"),
    ("exhibit", "Exhibit 1 — 000001", "Exhibit [FILE_NUMBER] — [BATES_NUMBER]"),
    ("exhibit-page", "Exhibit 1 — Case XYZ — 000001 — Page 1", "Exhibit [FILE_NUMBER] — [CASE] — [BATES_NUMBER] — Page [PAGE_ARABIC]"),
    ("number", "000001", "[BATES_NUMBER]"),
    ("custom", "Custom", ""),
]


def bates(ctx):
    style = ctx.param("style", "full")
    preset = {k: p for k, _, p in BATES_STYLES}.get(style, "")
    pattern = (ctx.param("pattern") or "").strip() if style == "custom" or not preset else preset
    if not pattern:
        raise TaskError("Enter the text to stamp, including [BATES_NUMBER]")
    case = (ctx.param("caseName") or "Case").strip()
    digits = max(1, min(12, _int(ctx.param("batesDigits"), 6)))
    number = max(0, _int(ctx.param("batesStartFrom"), 1))
    step = max(1, _int(ctx.param("batesIncrement"), 1))
    file_no = _int(ctx.param("fileCountStartFrom"), 1)
    location = ctx.param("pageLocation", "bottom-right")
    font = ctx.param("font", "helvetica")
    size = _num(ctx.param("fontSize"), 10) or 10
    color = hex_to_rgb(ctx.param("color"))
    add_margins = ctx.flag("addMargins")
    first_number = number
    for f, inp in enumerate(ctx.inputs):
        pdf = open_pdf(inp)
        for idx in range(len(pdf.pages)):
            ctx.check_cancelled()
            text = (pattern.replace("[BATES_NUMBER]", str(number).zfill(digits)).replace("[FILE_NUMBER]", str(file_no + f))
                    .replace("[PAGE_ARABIC]", str(idx + 1)).replace("[CASE]", case).replace("[BASE_NAME]", inp.stem))
            if add_margins:
                _shrink_for_margin(pdf, idx, location, _label_room(text, size))
            stamp(pdf, pdf.pages[idx], lambda c, w, h, t=text: _draw_label(c, w, h, t, location, font, size, color))
            number += step
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark(f"Stamped Bates numbers {str(first_number).zfill(digits)} to {str(number - step).zfill(digits)}")


register(Tool(
    type="batesNumbering", slug="bates-numbering-pdf", title="Bates numbering", icon="bates", category="stamp",
    tagline="Stamp sequential identification numbers across one or many legal documents.",
    handler=bates, keywords="legal exhibit case stamp numbering",
    options=[
        Opt("style", "Style", "select", [(k, label) for k, label, _ in BATES_STYLES], "full"),
        Opt("caseName", "Case name", "text", default="Case XYZ", show_if={"style": ["full", "exhibit-page"]}),
        Opt("pattern", "Custom text", "text", default="[CASE] [BATES_NUMBER]", show_if={"style": "custom"},
            help="Tokens: [BATES_NUMBER] [FILE_NUMBER] [PAGE_ARABIC] [CASE] [BASE_NAME]"),
        Opt("batesStartFrom", "Start at", "number", default=1, min=0),
        Opt("batesDigits", "Digits", "select", [("1", "1"), ("3", "3"), ("4", "4"), ("5", "5"), ("6", "6"), ("8", "8")], "6"),
        Opt("pageLocation", "Position", "select", LOCATIONS, "bottom-right"),
        Opt("fontSize", "Font size", "select", SIZES, "10", advanced=True),
        Opt("font", "Font", "radio", FONTS, "helvetica", advanced=True),
        Opt("color", "Color", "color", default="#000000", advanced=True),
        Opt("batesIncrement", "Increment", "number", default=1, min=1, advanced=True),
        Opt("fileCountStartFrom", "First exhibit number", "number", default=1, min=0, advanced=True),
        Opt("addMargins", "Shrink pages so the stamp doesn't overlap content", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# watermark


def watermark(ctx):
    pdfs = [i for i in ctx.inputs if not is_image(i.name, i.path)]
    images = [i for i in ctx.inputs if is_image(i.name, i.path)]
    kind = ctx.param("watermarkType", "text")
    text = (ctx.param("watermarkText") or "").strip()
    if kind == "image" and not images:
        raise TaskError("Add an image file to use as the watermark")
    if kind == "text" and not text:
        raise TaskError("Enter the watermark text")
    if not pdfs:
        raise TaskError("Add a PDF to watermark")
    opacity = max(0.02, min(1.0, _num(ctx.param("opacity"), 50) / 100))
    size = _num(ctx.param("fontSize"), 48) or 48
    color = hex_to_rgb(ctx.param("color"), (0.8, 0.1, 0.1))
    angle = _num(ctx.param("rotation"), 45)
    font = ctx.param("font", "helvetica")
    position = {"centered": "center", "middle": "center"}.get(ctx.param("pageLocation", "center"), ctx.param("pageLocation", "center"))
    under = ctx.param("layer", "over") == "under"
    img_scale = max(0.05, min(1.0, _num(ctx.param("imageScale"), 50) / 100))
    img_reader = None
    if kind == "image":
        from PIL import Image
        from reportlab.lib.utils import ImageReader

        pil = Image.open(images[0].path)
        pil.load()
        img_reader, img_size = ImageReader(pil), pil.size

    def draw(c, w, h):
        c.saveState()
        c.setFillAlpha(opacity)
        c.setStrokeAlpha(opacity)
        if position == "tile":
            spots = [(w * x / 3, h * y / 4) for x in (0.5, 1.5, 2.5) for y in (0.5, 1.5, 2.5, 3.5)]
        else:
            spots = [{"center": (w / 2, h / 2), "top": (w / 2, h * 0.85), "bottom": (w / 2, h * 0.15)}.get(position, (w / 2, h / 2))]
        for x, y in spots:
            c.saveState()
            c.translate(x, y)
            c.rotate(angle)
            if img_reader is not None:
                iw, ih = img_size
                k = min(w, h) * img_scale / max(iw, ih) * (0.45 if position == "tile" else 1)
                c.drawImage(img_reader, -iw * k / 2, -ih * k / 2, iw * k, ih * k, mask="auto")
            else:
                fs = size * (0.5 if position == "tile" else 1)
                lines = text.split("\n")
                # shrink text that would run off the page once rotated
                tw = max(text_width(line, font, fs, bold=True) for line in lines)
                th = fs * 1.2 * len(lines)
                t = math.radians(angle)
                bw = abs(tw * math.cos(t)) + abs(th * math.sin(t))
                bh = abs(tw * math.sin(t)) + abs(th * math.cos(t))
                room_w, room_h = (w / 3, h / 4) if position == "tile" else (w * 0.95, h * (0.95 if position == "center" else 0.3))
                k = min(1.0, room_w / bw if bw else 1, room_h / bh if bh else 1)
                fs *= k
                c.setFillColorRGB(*color)
                for i, line in enumerate(lines):
                    draw_text(c, 0, -fs * 0.35 + (len(lines) / 2 - i - 0.5) * fs * 1.2, line, font, fs, "center", bold=True)
            c.restoreState()
        c.restoreState()

    for inp in pdfs:
        pdf = open_pdf(inp)
        for i in pages_or_error(ctx.param("pages"), len(pdf.pages)):
            ctx.check_cancelled()
            stamp(pdf, pdf.pages[i - 1], draw, under=under)
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Watermark added")


register(Tool(
    type="watermark", slug="watermark-pdf", title="Watermark PDF", icon="watermark", category="stamp",
    tagline="Stamp text or an image over (or under) your pages, at any angle and transparency.",
    handler=watermark, accept=PDF + IMAGES, keywords="stamp confidential draft logo",
    options=[
        Opt("watermarkType", "Watermark", "radio", [("text", "Text"), ("image", "Image (upload it with your PDF)")], "text"),
        Opt("watermarkText", "Text", "textarea", default="CONFIDENTIAL", show_if={"watermarkType": "text"}),
        Opt("fontSize", "Font size", "number", default=48, min=6, max=300, show_if={"watermarkType": "text"}),
        Opt("color", "Color", "color", default="#d6336c", show_if={"watermarkType": "text"}),
        Opt("imageScale", "Image size (% of page)", "range", default=50, min=5, max=100, show_if={"watermarkType": "image"}),
        Opt("opacity", "Opacity (%)", "range", default=40, min=5, max=100),
        Opt("rotation", "Angle", "select", [("0", "0°"), ("30", "30°"), ("45", "45°"), ("60", "60°"), ("90", "90°"),
            ("-30", "−30°"), ("-45", "−45°"), ("-60", "−60°"), ("180", "180°")], "45"),
        Opt("pageLocation", "Position", "radio", [("center", "Center"), ("top", "Top"), ("bottom", "Bottom"), ("tile", "Tiled")], "center", advanced=True),
        Opt("layer", "Layer", "radio", [("over", "Over the content"), ("under", "Behind the content")], "over", advanced=True),
        Opt("font", "Font", "radio", FONTS, "helvetica", advanced=True),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))
