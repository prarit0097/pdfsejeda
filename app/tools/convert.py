"""Convert tools: PDF -> images/text/Excel/Word/PowerPoint, images -> PDF,
extract images, Word -> PDF (LibreOffice), HTML -> PDF (Chromium), OCR (Tesseract)."""
from __future__ import annotations

import csv
import functools
import html as html_lib
import io
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse

import pikepdf
import httpx

from ..jobs import InputFile, TaskError
from ..security import UnsafeUrl, _check_host, _pinned, resolve_public
from .common import PAGE_SIZES_PT, open_pdf, output_name, pages_or_error, pdfium_doc
from .imaging import image_to_pdf
from .registry import IMAGES, Opt, Tool, register


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def find_binary(names: list[str], extra: list[str] = ()) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for p in extra:
        if os.path.exists(p):
            return p
    return None


def soffice_path():
    # The Windows console launcher reports completion/errors reliably; the GUI
    # launcher can return early or block when invoked from a server process.
    names = ["soffice.com", "soffice", "libreoffice"] if sys.platform == "win32" else ["soffice", "libreoffice"]
    return find_binary(names, [r"C:\Program Files\LibreOffice\program\soffice.com",
                                                    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
                                                    r"C:\Program Files\LibreOffice\program\soffice.exe",
                                                    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                                                    "/Applications/LibreOffice.app/Contents/MacOS/soffice"])


def tesseract_path():
    return find_binary(["tesseract"], [r"C:\Program Files\Tesseract-OCR\tesseract.exe", "/opt/homebrew/bin/tesseract"])


def _run(cmd: list[str], timeout: float, **kw) -> subprocess.CompletedProcess:
    """subprocess.run that also kills child processes on timeout (soffice.exe starts soffice.bin)."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
                            start_new_session=sys.platform != "win32", **kw)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        proc.communicate()
        raise
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, cmd, out, err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


# Renders bigger than this many pixels are scaled down (an A0 page at 600 dpi is ~560 MP).
MAX_RENDER_PIXELS = 60_000_000


def _safe_dpi(page, dpi: float) -> float:
    w, h = page.get_size()
    px = (w * dpi / 72) * (h * dpi / 72)
    if px > MAX_RENDER_PIXELS:
        dpi = dpi * math.sqrt(MAX_RENDER_PIXELS / px)
    return dpi


# ---------------------------------------------------------------------------
# text direction helpers


def _horizontal_text(page) -> bool:
    """True when most characters of a pypdfium2 page run left-to-right in *unrotated*
    page space, i.e. /Rotate turns normal text sideways and layout analysis should
    ignore it."""
    import pypdfium2.raw as pdfium_c

    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        total = horiz = 0
        for i in range(0, n, max(1, n // 400)):
            if pdfium_c.FPDFText_GetUnicode(tp.raw, i) in (9, 10, 13, 32):
                continue
            a = pdfium_c.FPDFText_GetCharAngle(tp.raw, i)
            if a < 0:
                continue
            total += 1
            horiz += a < 0.3 or a > 2 * math.pi - 0.3
        return total > 0 and horiz * 2 > total
    finally:
        tp.close()


def _page_text(page) -> str:
    """Plain text of a pypdfium2 page in reading order (ignores a /Rotate that only
    turns ordinary horizontal text sideways)."""
    if page.get_rotation() and _horizontal_text(page):
        page.set_rotation(0)
    tp = page.get_textpage()
    try:
        return tp.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
    finally:
        tp.close()


def _upright_source(ctx, inp) -> InputFile:
    """An unencrypted copy of the PDF where pages whose /Rotate only turns horizontal
    text sideways are un-rotated, so pdfplumber sees normal text lines."""
    pdf = open_pdf(inp)
    changed = pdf.is_encrypted
    with pdfium_doc(inp) as doc:
        for i, page in enumerate(pdf.pages):
            if doc[i].get_rotation() and _horizontal_text(doc[i]):
                page.Rotate = 0
                changed = True
    if not changed:
        pdf.close()
        return inp
    path = ctx.temp(f"upright-{inp.id}.pdf")
    pdf.save(path)
    pdf.close()
    return InputFile(inp.id, inp.name, path, None)


# ---------------------------------------------------------------------------
# PDF -> images


def pdf_to_image(ctx):
    fmt = (ctx.param("imageFormat") or "jpg").lower()
    fmt = {"jpeg": "jpg", "tif": "tiff"}.get(fmt, fmt)
    dpi = int(_num(ctx.param("resolution"), 150) or 150)
    dpi = max(36, min(dpi, 600))
    color = ctx.param("imageColorType", "rgb")
    single_tiff = fmt == "tiff" and ctx.flag("tiffSingleFileWithAllPages")
    pages_spec = "1-" if ctx.flag("allPages") else ctx.param("pages")
    reduced = False
    for inp in ctx.inputs:
        frames = []
        with pdfium_doc(inp) as doc:
            try:
                doc.init_forms()  # so filled-in form fields are drawn
            except Exception:
                pass
            sel = pages_or_error(pages_spec, len(doc))
            for p in sel:
                ctx.check_cancelled()
                page = doc[p - 1]
                pdpi = _safe_dpi(page, dpi)
                reduced |= pdpi < dpi
                pil = page.render(scale=pdpi / 72, draw_annots=True, may_draw_forms=True).to_pil()
                if color == "grayscale":
                    pil = pil.convert("L")
                elif color == "black_white":
                    # plain threshold: dithering turns anti-aliased text into speckles
                    pil = pil.convert("L").point(lambda v: 255 if v > 150 else 0).convert("1", dither=0)
                else:
                    pil = pil.convert("RGB")
                if single_tiff:
                    frames.append(pil)
                    continue
                ext = {"jpg": "jpg", "png": "png", "tiff": "tif"}.get(fmt, "jpg")
                out = ctx.output(f"{inp.stem}-{p}.{ext}")
                rd = round(pdpi)
                if ext == "jpg":
                    (pil if pil.mode != "1" else pil.convert("L")).save(out, "JPEG", quality=90, dpi=(rd, rd))
                elif ext == "png":
                    pil.save(out, "PNG", optimize=True, dpi=(rd, rd))
                else:
                    pil.save(out, "TIFF", compression="group4" if pil.mode == "1" else "tiff_lzw", dpi=(rd, rd))
        if single_tiff and frames:
            frames[0].save(ctx.output(f"{inp.stem}.tif"), "TIFF", save_all=True, append_images=frames[1:],
                           compression="group4" if color == "black_white" else "tiff_lzw", dpi=(dpi, dpi))
    if reduced:
        ctx.warn("Some pages are very large, so they were rendered at a lower resolution.")
    ctx.remark("Pages converted to images")


register(Tool(
    type="pdfToImage", slug="pdf-to-jpg", title="PDF to JPG", icon="image", category="from_pdf", popular=True,
    tagline="Turn each page into a JPG, PNG or TIFF image.",
    handler=pdf_to_image, page_ui="select", keywords="pdf to image png tiff jpeg picture convert",
    options=[
        Opt("pages", "Pages", "pages", placeholder="all pages"),
        Opt("imageFormat", "Format", "radio", [("jpg", "JPG"), ("png", "PNG"), ("tiff", "TIFF")], "jpg"),
        Opt("resolution", "Resolution", "radio", [("75", "75 dpi"), ("150", "150 dpi"), ("220", "220 dpi"), ("300", "300 dpi")], "150"),
        Opt("imageColorType", "Colors", "radio", [("rgb", "Color"), ("grayscale", "Grayscale"), ("black_white", "Black & white")], "rgb", advanced=True),
        Opt("tiffSingleFileWithAllPages", "One multi-page TIFF instead of one file per page", "checkbox", show_if={"imageFormat": "tiff"}),
    ],
))


# ---------------------------------------------------------------------------
# images -> PDF


_IMG_EXT = {"JPEG": ".jpg", "MPO": ".jpg", "PNG": ".png", "GIF": ".gif", "TIFF": ".tif", "BMP": ".bmp", "WEBP": ".webp"}


def _image_source(ctx, inp, n: int) -> Path:
    """Stored uploads have no file extension, but image_to_pdf picks JPEG vs PNG
    re-encoding from the suffix. Hand it a copy named after the real format so
    JPEGs stay JPEG (small output) and CMYK images never go through PNG."""
    from PIL import Image

    try:
        with Image.open(inp.path) as im:
            fmt, mode = (im.format or "").upper(), im.mode
    except Exception:
        raise TaskError(f"Could not read the image '{inp.name}'. It may be damaged or not an image.") from None
    ext = _IMG_EXT.get(fmt, ".png")
    src = ctx.temp(f"image-{n}{ext}")
    if mode == "CMYK" and ext != ".jpg":  # PNG can't hold CMYK
        with Image.open(inp.path) as im:
            dpi = im.info.get("dpi", (96, 96))
            frames = []
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                frames.append(im.convert("RGB"))
        src = ctx.temp(f"image-{n}.tif")
        frames[0].save(src, "TIFF", save_all=True, append_images=frames[1:], dpi=dpi)
        return src
    try:
        os.link(inp.path, src)
    except OSError:
        shutil.copyfile(inp.path, src)
    return src


def jpg_to_pdf(ctx):
    size = (ctx.param("pageSize") or "auto").lower()
    orientation = ctx.param("pageOrientation", "auto")
    margin = {"none": 0, "small": 20, "big": 50}.get(str(ctx.param("pageMargin", "none")), _num(ctx.param("pageMargin"), 0))
    margin = max(0.0, min(margin, 144.0))
    custom = None
    if size == "custom":
        unit = 72 if ctx.param("unit", "inch") == "inch" else 72 / 2.54
        w = _num(ctx.param("pageSizeWidth") or ctx.param("pageSizeCustomWidth"))
        h = _num(ctx.param("pageSizeHeight") or ctx.param("pageSizeCustomHeight"))
        custom = (w * unit, h * unit)
        if custom[0] < 36 or custom[1] < 36:
            raise TaskError("Enter a custom page width and height")
        if custom[0] > 14400 or custom[1] > 14400:
            raise TaskError("The custom page size is too large (200 inches at most)")
    rotations = ctx.params.get("rotations") or []
    merge = ctx.flag("mergeOutputs", True)
    combined = pikepdf.new()
    for n, inp in enumerate(ctx.inputs):
        ctx.check_cancelled()
        rot = int(_num(rotations[n] if n < len(rotations) else 0))
        if inp.name.lower().endswith(".pdf"):
            part = open_pdf(inp)
        else:
            part = image_to_pdf(_image_source(ctx, inp, n), size, orientation, margin, custom, rotate=rot)
        if merge:
            combined.pages.extend(part.pages)
        else:
            part.save(ctx.output(f"{inp.stem}.pdf"))
    if merge:
        name = f"{ctx.inputs[0].stem}.pdf" if len(ctx.inputs) == 1 else "images.pdf"
        combined.save(ctx.output(name))
    ctx.remark(f"Converted {len(ctx.inputs)} image{'s' if len(ctx.inputs) != 1 else ''}")


register(Tool(
    type="jpgToPdf", slug="jpg-to-pdf", title="JPG to PDF", icon="images", category="to_pdf", popular=True,
    tagline="Turn photos and images (JPG, PNG, GIF, TIFF, BMP, WEBP) into a PDF.",
    handler=jpg_to_pdf, accept=IMAGES + ["pdf"], page_ui="files", keywords="image to pdf png photo picture convert",
    options=[
        Opt("pageSize", "Page size", "select", [("auto", "Same as image"), ("a4", "A4"), ("letter", "Letter"), ("legal", "Legal"),
            ("a5", "A5"), ("a3", "A3"), ("a2", "A2"), ("a1", "A1"), ("tabloid", "Tabloid"), ("ledger", "Ledger"),
            ("executive", "Executive"), ("custom", "Custom")], "auto"),
        Opt("pageOrientation", "Orientation", "radio", [("auto", "Automatic"), ("portrait", "Portrait"), ("landscape", "Landscape")], "auto"),
        Opt("pageMargin", "Margin", "radio", [("none", "None"), ("small", "Small"), ("big", "Big")], "none"),
        Opt("unit", "Unit", "radio", [("inch", "inch"), ("cm", "cm")], "inch", show_if={"pageSize": "custom"}),
        Opt("pageSizeWidth", "Width", "number", step=0.1, show_if={"pageSize": "custom"}),
        Opt("pageSizeHeight", "Height", "number", step=0.1, show_if={"pageSize": "custom"}),
        Opt("mergeOutputs", "Put all images in one PDF", "checkbox", default=True, advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# extract images / text


def extract_images(ctx):
    from pikepdf import PdfImage

    from .modify import iter_image_xobjects

    count = 0
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        n = 0
        for xo, _ in iter_image_xobjects(pdf):
            ctx.check_cancelled()
            if xo.get("/ImageMask"):  # stencil masks are shapes, not pictures
                continue
            try:
                img = PdfImage(xo)
                if img.width < 16 or img.height < 16:
                    continue
            except Exception:
                continue
            n += 1
            target = ctx.temp(f"x-{inp.id}-{n}")
            try:
                produced = Path(img.extract_to(fileprefix=str(target)))
                if produced.suffix.lower() in (".jpg", ".jpeg") and _is_inverted_cmyk(xo):
                    produced.unlink()
                    raise ValueError("inverted CMYK")
            except Exception:
                try:
                    pil = img.as_pil_image()
                    if pil.mode == "CMYK" and _is_inverted_cmyk(xo):
                        from PIL import ImageChops

                        pil = ImageChops.invert(pil)
                    pil = pil.convert("RGBA" if pil.mode in ("RGBA", "LA", "P") else "RGB" if pil.mode not in ("L", "1") else pil.mode)
                    produced = ctx.temp(f"x-{inp.id}-{n}.png")
                    pil.save(produced)
                except Exception:
                    n -= 1
                    continue
            shutil.move(produced, ctx.output(f"{inp.stem}-image-{n}{produced.suffix}"))
            count += 1
    if not count:
        raise TaskError("No images were found in this PDF")
    ctx.remark(f"Extracted {count} image{'s' if count != 1 else ''}")


def _is_inverted_cmyk(xo) -> bool:
    d = xo.get("/Decode")
    return d is not None and len(d) >= 2 and float(d[0]) == 1 and float(d[1]) == 0


register(Tool(
    type="extractImages", slug="extract-images-from-pdf", title="Extract images", icon="images", category="from_pdf",
    tagline="Save every picture embedded in a PDF as a separate image file.",
    handler=extract_images, keywords="images pictures photos save export",
))


def extract_text(ctx):
    for inp in ctx.inputs:
        parts = []
        with pdfium_doc(inp) as doc:
            sel = pages_or_error(ctx.param("pages"), len(doc))
            for p in sel:
                ctx.check_cancelled()
                parts.append(_page_text(doc[p - 1]).strip())
        text = "\n\n\f".join(parts) if ctx.flag("pageBreaks") else "\n\n".join(parts)
        if not text.strip():
            ctx.warn(f"'{inp.name}' contains no selectable text. If it is a scan, run OCR first.")
        ctx.output(f"{inp.stem}.txt").write_text(text, encoding="utf-8", newline="\n")
    ctx.remark("Text extracted")


register(Tool(
    type="extractText", slug="extract-text-from-pdf", title="PDF to text", icon="text", category="from_pdf",
    tagline="Copy all the text out of a PDF into a plain .txt file.",
    handler=extract_text, keywords="text txt copy extract",
    options=[
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
        Opt("pageBreaks", "Mark page breaks with a form-feed character", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# Layout analysis shared by PDF -> Excel and PDF -> Word.
# Works on pdfplumber word dicts (x0, x1, top, bottom, size, fontname, text).

_LIST_MARK = re.compile(r"^(?:[•●▪◦■□➢►\-–*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)]|[ivxIVX]{1,4}[.)])$")


def _page_words(page) -> list[dict]:
    words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False, use_text_flow=False)
    upright = [w for w in words if w.get("upright", True)]
    if len(upright) * 2 >= len(words):
        words = upright
    for i, w in enumerate(words):
        w["kind"], w["i"] = "word", i
    return words


def _median_size(words, default=10.0) -> float:
    return statistics.median(w["size"] for w in words) if words else default


def _lines_of(words) -> list[dict]:
    """Group words into lines (vertical centres close together), words sorted left to right."""
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        mid = (w["top"] + w["bottom"]) / 2
        if lines and abs(lines[-1]["mid"] - mid) <= max(2.0, 0.45 * min(lines[-1]["size"], w["size"])):
            ln = lines[-1]
            ln["words"].append(w)
            ln["top"], ln["bottom"] = min(ln["top"], w["top"]), max(ln["bottom"], w["bottom"])
            ln["x0"], ln["x1"] = min(ln["x0"], w["x0"]), max(ln["x1"], w["x1"])
            ln["size"] = max(ln["size"], w["size"])
        else:
            lines.append({"mid": mid, "top": w["top"], "bottom": w["bottom"], "x0": w["x0"], "x1": w["x1"],
                          "size": w["size"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
    return lines


def _chunks(line, gap: float) -> list[dict]:
    """Split a line into runs of words separated by gaps wider than `gap`."""
    out: list[dict] = []
    for w in line["words"]:
        if out and w["x0"] - out[-1]["x1"] <= gap:
            out[-1]["words"].append(w)
            out[-1]["x1"] = max(out[-1]["x1"], w["x1"])
        else:
            out.append({"x0": w["x0"], "x1": w["x1"], "words": [w]})
    return out


def _text_tables(words) -> list[dict]:
    """Find tables without ruling lines: consecutive lines split into aligned columns
    by wide gaps. Prose (long cells) and plain numbered lists are rejected."""
    lines = _lines_of(words)
    for ln in lines:
        ln["chunks"] = _chunks(ln, max(6.0, ln["size"] * 1.0))
    runs, cur = [], []
    for k, ln in enumerate(lines):
        multi = len(ln["chunks"]) >= 2
        near = cur and ln["top"] - cur[-1]["bottom"] <= 2.2 * ln["size"]
        if multi and (near or not cur):
            cur.append(ln)
            continue
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        sandwiched = (cur and near and not multi and len(ln["words"]) <= 4 and nxt is not None
                      and len(nxt["chunks"]) >= 2 and nxt["top"] - ln["bottom"] <= 2.2 * ln["size"])
        if sandwiched:
            cur.append(ln)
            continue
        if len(cur) >= 2:
            runs.append(cur)
        cur = [ln] if multi else []
    if len(cur) >= 2:
        runs.append(cur)

    tables = []
    for run in runs:
        t = _build_text_table(run)
        if t:
            tables.append(t)
    return tables


def _build_text_table(run) -> dict | None:
    spans = sorted((c["x0"], c["x1"]) for ln in run for c in ln["chunks"])
    cols: list[list[float]] = []
    for a, b in spans:
        if cols and a <= cols[-1][1] + 1:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    max_chunks = max(len(ln["chunks"]) for ln in run)
    if len(cols) < 2 or len(cols) > max_chunks + 1:
        return None
    rows = []
    for ln in run:
        cells = [[] for _ in cols]
        for w in ln["words"]:
            cx = (w["x0"] + w["x1"]) / 2
            k = next((i for i, (a, b) in enumerate(cols) if a - 1 <= cx <= b + 1), None)
            if k is None:
                k = min(range(len(cols)), key=lambda i: abs((cols[i][0] + cols[i][1]) / 2 - cx))
            cells[k].append(w["text"])
        rows.append([" ".join(c) for c in cells])
    filled = [c for r in rows for c in r if c]
    if sum(1 for r in rows if sum(1 for c in r if c) >= 2) < 2:
        return None
    long_cells = sum(1 for c in filled if len(c.split()) > 6)
    if long_cells > 0.15 * len(filled) or statistics.mean(len(c.split()) for c in filled) > 4:
        return None
    if len(cols) == 2 and all(_LIST_MARK.match(r[0]) for r in rows if r[0]):
        return None
    ws = [w for ln in run for w in ln["words"]]
    return {"kind": "table", "rows": rows, "ruled": False, "ids": {w["i"] for w in ws},
            "x0": min(w["x0"] for w in ws), "x1": max(w["x1"] for w in ws),
            "top": min(w["top"] for w in ws), "bottom": max(w["bottom"] for w in ws)}


def _ruled_tables(page) -> list[dict]:
    out = []
    for t in page.find_tables():
        rows = [[(c or "").strip() for c in row] for row in t.extract()]
        rows = [r for r in rows if any(r)]
        if not rows or max(len(r) for r in rows) < 2:
            continue
        x0, top, x1, bottom = t.bbox
        out.append({"kind": "table", "rows": rows, "ruled": True, "x0": x0, "top": top, "x1": x1, "bottom": bottom})
    return out


def _inside(w, box, pad: float = 1.0) -> bool:
    cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
    return box["x0"] - pad <= cx <= box["x1"] + pad and box["top"] - pad <= cy <= box["bottom"] + pad


def _page_tables(page):
    """(tables sorted top to bottom, words that are not part of any table)."""
    ruled = _ruled_tables(page)
    words = [w for w in _page_words(page) if not any(_inside(w, t) for t in ruled)]
    text_tables = _text_tables(words)
    taken = set().union(*(t["ids"] for t in text_tables)) if text_tables else set()
    words = [w for w in words if w["i"] not in taken]
    return sorted(ruled + text_tables, key=lambda t: t["top"]), words


def _split_axis(items, lo: str, hi: str, min_gap: float):
    its = sorted(items, key=lambda i: i[lo])
    groups, gaps = [[its[0]]], []
    end = its[0][hi]
    for it in its[1:]:
        if it[lo] - end >= min_gap:
            gaps.append(it[lo] - end)
            groups.append([it])
        else:
            groups[-1].append(it)
        end = max(end, it[hi])
    return groups, gaps


def _line_count(items, size: float) -> int:
    tops = sorted(i["top"] for i in items if i["kind"] == "word")
    return sum(1 for a, b in zip([-1e9] + tops, tops) if b - a > 0.5 * size)


def _xy_cut(items, size: float) -> list[list[dict]]:
    """Recursive XY-cut: split at column gutters first, then at the widest blank
    horizontal bands. Returns leaf regions in reading order."""
    leaves: list[list[dict]] = []

    def rec(its, depth):
        if len(its) < 2 or depth > 80:
            leaves.append(its)
            return
        width = max(i["x1"] for i in its) - min(i["x0"] for i in its)
        cols, _ = _split_axis(its, "x0", "x1", max(9.0, size))
        if len(cols) > 1:
            widths = [max(i["x1"] for i in c) - min(i["x0"] for i in c) for c in cols]
            if all(_line_count(c, size) >= 2 for c in cols) and min(widths) >= max(6 * size, 0.12 * width):
                for c in cols:
                    rec(c, depth + 1)
                return
        rows, gaps = _split_axis(its, "top", "bottom", max(2.0, size * 0.5))
        if len(rows) > 1:
            m = max(gaps)
            parts = [rows[0]]
            for g, grp in zip(gaps, rows[1:]):
                if g >= 0.8 * m:
                    parts.append(grp)
                else:
                    parts[-1] = parts[-1] + grp
            if len(parts) > 1:
                for p in parts:
                    rec(p, depth + 1)
                return
        leaves.append(its)

    if items:
        rec(items, 0)
    return leaves


def _style_of(w):
    f = w.get("fontname", "").lower()
    return ("bold" in f or "black" in f or "heavy" in f or "semibold" in f, "italic" in f or "oblique" in f)


def _paragraphs(words, bounds=None) -> list[dict]:
    """Group the words of one region into lines, then lines into paragraphs."""
    lines = _lines_of(words)
    if not lines:
        return []
    rx0 = min(ln["x0"] for ln in lines)
    rx1 = max(ln["x1"] for ln in lines)
    paras: list[dict] = []
    prev_line = None
    for ln in lines:
        segs = []
        for w in ln["words"]:
            b, it = _style_of(w)
            if segs and segs[-1][1] == b and segs[-1][2] == it and abs(segs[-1][3] - w["size"]) < 0.6:
                segs[-1][0] += " " + w["text"]
            else:
                segs.append([(" " if segs else "") + w["text"], b, it, w["size"]])
        text = " ".join(w["text"] for w in ln["words"])
        bold = all(s[1] for s in segs)
        size = ln["size"]
        p = paras[-1] if paras else None
        new = p is None
        if p is not None:
            gap = ln["top"] - p["bottom"]
            prev_short = prev_line["x1"] < rx1 - max(3 * size, 0.15 * (rx1 - rx0))
            new = (abs(p["size"] - size) >= 1 or gap > 0.6 * size or gap < -0.5 * size or p["bold"] != bold
                   or _LIST_MARK.match(ln["words"][0]["text"]) is not None
                   or (prev_short and re.search(r"[.!?:;]['\")\]]?$", p["text"]) is not None))
        if new:
            paras.append({"top": ln["top"], "bottom": ln["bottom"], "x0": ln["x0"], "x1": ln["x1"], "text": text,
                          "size": size, "bold": bold, "segs": [list(s) for s in segs], "lines": [ln]})
        else:
            if p["text"].endswith("-") and len(p["text"]) > 2 and p["text"][-2].isalpha() and text[:1].islower():
                p["text"] = p["text"][:-1] + text
                p["segs"][-1][0] = p["segs"][-1][0][:-1]
                segs[0][0] = segs[0][0].lstrip()
            else:
                p["text"] += " " + text
                segs[0][0] = " " + segs[0][0].lstrip()
            for s in segs:
                last = p["segs"][-1]
                if last[1] == s[1] and last[2] == s[2] and abs(last[3] - s[3]) < 0.6:
                    last[0] += s[0]
                else:
                    p["segs"].append(list(s))
            p["bottom"] = max(p["bottom"], ln["bottom"])
            p["x0"], p["x1"] = min(p["x0"], ln["x0"]), max(p["x1"], ln["x1"])
            p["lines"].append(ln)
        prev_line = ln
    if bounds:
        bx0, bx1 = bounds
        mid, tol = (bx0 + bx1) / 2, max(6.0, 0.03 * (bx1 - bx0))
        for p in paras:
            p["center"] = all(abs((ln["x0"] + ln["x1"]) / 2 - mid) <= tol and (ln["x1"] - ln["x0"]) < 0.85 * (bx1 - bx0)
                              and ln["x0"] - bx0 > 3 * p["size"] for ln in p["lines"])
    return paras


def _page_blocks(page) -> list[dict]:
    """Ordered blocks of a pdfplumber page: paragraphs, tables and pictures."""
    tables, words = _page_tables(page)
    images = []
    for img in page.images:
        w, h = img["x1"] - img["x0"], img["bottom"] - img["top"]
        if w <= 24 or h <= 24:
            continue
        box = {"kind": "image", "x0": max(0.0, float(img["x0"])), "x1": min(float(page.width), float(img["x1"])),
               "top": max(0.0, float(img["top"])), "bottom": min(float(page.height), float(img["bottom"]))}
        if box["x1"] - box["x0"] < 8 or box["bottom"] - box["top"] < 8:
            continue
        if sum(1 for wd in words if _inside(wd, box, 0)) >= 3:
            continue  # a background picture under the text (e.g. a scan with an OCR layer)
        if any(abs(b["x0"] - box["x0"]) < 1 and abs(b["top"] - box["top"]) < 1 and abs(b["x1"] - box["x1"]) < 1 for b in images):
            continue
        images.append(box)
    size = _median_size(words)
    bounds = (min(w["x0"] for w in words), max(w["x1"] for w in words)) if words else None
    blocks = []
    for leaf in _xy_cut(words + tables + images, size):
        ws = [i for i in leaf if i["kind"] == "word"]
        items = [i for i in leaf if i["kind"] != "word"]
        for p in _paragraphs(ws, bounds):
            p["kind"] = "text"
            items.append(p)
        blocks += sorted(items, key=lambda b: b["top"])
    return blocks


# ---------------------------------------------------------------------------
# PDF -> Excel / CSV

_CURRENCY = "$€£¥₹"
_NUM = re.compile(r"^(?P<open>\()?(?P<sign>[-−])?\s*(?P<cur>[$€£¥₹])?\s*(?P<sign2>[-−])?"
                  r"(?P<num>\d{1,3}(?:(?P<sep>[, \u00a0\u202f])\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
                  r"\s*(?P<pct>%)?\s*(?P<cur2>[$€£¥₹])?(?P<close>\))?$")
_EU_NUM = re.compile(r"^(?P<sign>[-−])?\s*(?P<cur>[€£$])?\s*(?P<num>\d{1,3}(?:\.\d{3})+,\d+|\d+,\d{1,2})\s*(?P<cur2>[€£$])?$")


def _cell(v: str):
    """Cell text -> (value, number_format). Numbers like 1,200 / $4.50 / (250) / 12.5% become numbers."""
    s = (v or "").replace("\n", " ").strip()
    if not s or len(s) > 40:
        return s, None
    m = _NUM.match(s)
    eu = None if m else _EU_NUM.match(s)
    if not m and not eu:
        return s, None
    if m and bool(m["open"]) != bool(m["close"]):
        return s, None
    g = m or eu
    digits = g["num"]
    if m:
        plain = re.sub(r"[, \u00a0\u202f]", "", digits)
    else:
        plain = digits.replace(".", "").replace(",", ".")
    intpart = plain.split(".")[0]
    if (len(intpart) > 1 and intpart.startswith("0")) or len(plain.replace(".", "")) > 15:
        return s, None  # codes with leading zeros, long ids
    try:
        val = float(plain)
    except ValueError:
        return s, None
    neg = bool(g["sign"]) or (m is not None and (bool(m["open"]) or bool(m["sign2"])))
    if neg:
        val = -val
    decimals = len(plain.split(".")[1]) if "." in plain else 0
    pct = m is not None and m["pct"]
    cur = g["cur"] or g["cur2"]
    grouped = (m is not None and m["sep"]) or (eu is not None and "." in digits)
    if pct:
        val /= 100
        return val, "0" + ("." + "0" * decimals if decimals else "") + "%"
    if decimals == 0 and not cur:
        val = int(val)
    fmt = ("#,##0" if grouped or cur else "0") + ("." + "0" * decimals if decimals else "")
    if cur:
        fmt = f'"{cur}"{fmt}'
    if m and m["open"]:
        fmt = f"{fmt};({fmt})"
    return val, (None if fmt == "0" else fmt)


def _page_lines_as_rows(page) -> list[list[str]]:
    rows = []
    for ln in _lines_of(_page_words(page)):
        rows.append([" ".join(w["text"] for w in c["words"]) for c in _chunks(ln, max(6.0, ln["size"] * 1.2))])
    return rows


def pdf_to_excel(ctx):
    import pdfplumber
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    fmt = ctx.param("exportFormat", "excel")
    single = ctx.flag("singleSheet")
    total_tables = 0
    for inp in ctx.inputs:
        src = _upright_source(ctx, inp)
        tables = []  # (page, rows)
        fallback = []  # (page, rows) when no table is found anywhere
        with pdfplumber.open(str(src.path), password=src.password or "") as doc:
            sel = pages_or_error(ctx.param("pages"), len(doc.pages))
            for p in sel:
                ctx.check_cancelled()
                page = doc.pages[p - 1]
                found, _ = _page_tables(page)
                tables += [(p, t["rows"]) for t in found]
            if not tables:
                for p in sel:
                    rows = _page_lines_as_rows(doc.pages[p - 1])
                    if rows:
                        fallback.append((p, rows))
        if not tables and not fallback:
            raise TaskError(f"No text or tables were found in '{inp.name}'. If it is a scan, run OCR first.")
        if not tables:
            ctx.warn(f"No tables were found in '{inp.name}', so its text was exported line by line.")
            groups = fallback
            names = [f"Page {p}" for p, _ in fallback]
        else:
            groups = tables
            names = [f"Page {p} table {i + 1}" for i, (p, _) in enumerate(tables)]
        total_tables += len(tables)
        if fmt == "csv":
            if single or len(groups) == 1:
                out = [r for _, rows in groups for r in rows + [[]]][:-1]
                _write_csv(ctx.output(f"{inp.stem}.csv"), out)
            else:
                for (p, rows), name in zip(groups, names):
                    suffix = re.sub(r"\W+", "-", name.lower()).replace("page-", "p").replace("-table-", "-t")
                    _write_csv(ctx.output(f"{inp.stem}-{suffix}.csv"), rows)
            continue
        wb = Workbook()
        wb.remove(wb.active)
        ws = None
        widths: dict = {}
        for (p, rows), name in zip(groups, names):
            if ws is None or not single:
                ws = wb.create_sheet(("Tables" if single and tables else "Text" if single else name)[:31])
                widths = {}
                r0 = 1
            else:
                r0 = ws.max_row + 2
            for r, row in enumerate(rows):
                for c, v in enumerate(row):
                    val, nf = _cell(v)
                    if val == "":
                        continue
                    cell = ws.cell(row=r0 + r, column=c + 1, value=val)
                    if nf:
                        cell.number_format = nf
                    if r == 0 and tables:
                        cell.font = Font(bold=True)
                    widths[c] = max(widths.get(c, 8), len(str(v)) + 2)
            for c, wd in widths.items():
                ws.column_dimensions[get_column_letter(c + 1)].width = min(60, wd)
        wb.save(ctx.output(f"{inp.stem}.xlsx"))
    if total_tables:
        ctx.remark(f"Found {total_tables} table{'s' if total_tables != 1 else ''}")
    else:
        ctx.remark("Text exported")


def _write_csv(path: Path, rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")


register(Tool(
    type="pdfToExcelNext", slug="pdf-to-excel", title="PDF to Excel", icon="table", category="from_pdf", popular=True,
    tagline="Pull tables out of a PDF into an Excel workbook or CSV files.",
    handler=pdf_to_excel, keywords="xlsx csv table spreadsheet convert",
    options=[
        Opt("exportFormat", "Format", "radio", [("excel", "Excel (.xlsx)"), ("csv", "CSV")], "excel"),
        Opt("singleSheet", "Put all tables in one sheet / file", "checkbox", advanced=True),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# PDF -> Word

_FAMILIES = {"helvetica": "Arial", "arial": "Arial", "times": "Times New Roman", "courier": "Courier New",
             "calibri": "Calibri", "cambria": "Cambria", "georgia": "Georgia", "verdana": "Verdana",
             "garamond": "Garamond", "tahoma": "Tahoma", "trebuchet": "Trebuchet MS", "dejavusans": "DejaVu Sans",
             "liberationsans": "Arial", "liberationserif": "Times New Roman", "roboto": "Roboto", "opensans": "Open Sans"}


def _family(fontname: str) -> str | None:
    base = fontname.split("+", 1)[-1].lower().replace(" ", "").replace("-", "").replace(",", "")
    for key, fam in _FAMILIES.items():
        if base.startswith(key):
            return fam
    return None


def _body_font(doc):
    sizes: dict = {}
    fams: dict = {}
    for page in doc.pages[:6]:
        for ch in page.chars[:4000]:
            s = round(ch["size"] * 2) / 2
            sizes[s] = sizes.get(s, 0) + 1
            f = _family(ch.get("fontname", ""))
            if f:
                fams[f] = fams.get(f, 0) + 1
    body = max(sizes, key=sizes.get) if sizes else 11
    fam = max(fams, key=fams.get) if fams else None
    return body, fam


def pdf_to_word(ctx):
    import pdfplumber
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt

    for inp in ctx.inputs:
        src = _upright_source(ctx, inp)
        document = Document()
        with pdfplumber.open(str(src.path)) as doc, pdfium_doc(src) as pdoc:
            body, family = _body_font(doc)
            normal = document.styles["Normal"]
            normal.font.size = Pt(body)
            if family:
                normal.font.name = family
            normal.paragraph_format.space_after = Pt(max(2, round(body * 0.5)))
            first = doc.pages[0]
            pw, ph = float(first.width), float(first.height)
            sec = document.sections[0]
            sec.page_width, sec.page_height = Pt(min(max(pw, 144), 1584)), Pt(min(max(ph, 144), 1584))
            margin = 54 if pw >= 400 else 28
            sec.left_margin = sec.right_margin = Pt(margin)
            sec.top_margin = sec.bottom_margin = Pt(min(margin, 54))
            usable = max(72.0, min(pw, 1584) - 2 * margin)
            any_text = False
            pictures = 0
            for pi, page in enumerate(doc.pages):
                ctx.check_cancelled()
                if pi:
                    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
                for b in _page_blocks(page):
                    kind = b["kind"]
                    if kind == "table":
                        rows = b["rows"]
                        ncols = max(len(r) for r in rows)
                        table = document.add_table(rows=len(rows), cols=ncols)
                        if b["ruled"]:
                            table.style = "Table Grid"
                        for r, row in enumerate(rows):
                            for c, v in enumerate(row):
                                table.cell(r, c).text = (v or "").strip()
                        any_text = True
                    elif kind == "image":
                        x0, top, x1, bottom = b["x0"], b["top"], b["x1"], b["bottom"]
                        ppage = pdoc[pi]
                        scale = 2 if (x1 - x0) * (bottom - top) < 400_000 else 1
                        pil = ppage.render(scale=scale, crop=(x0, float(page.height) - bottom, float(page.width) - x1, top)).to_pil()
                        buf = io.BytesIO()
                        pil.convert("RGB").save(buf, "PNG")
                        buf.seek(0)
                        document.add_picture(buf, width=Pt(min(x1 - x0, usable)))
                        pictures += 1
                    else:
                        any_text = True
                        _emit_paragraph(document, b, body, Pt, WD_ALIGN_PARAGRAPH)
            if not any_text:
                ctx.warn(f"'{inp.name}' has no selectable text{' (only pictures)' if pictures else ''}. "
                         "If it is a scan, run OCR first to get editable text.")
        document.save(ctx.output(f"{inp.stem}.docx"))
    ctx.remark("Converted to Word")


def _emit_paragraph(document, b, body, Pt, WD_ALIGN_PARAGRAPH):
    size, text = b["size"], b["text"]
    level = 1 if size >= body + 5 else 2 if size >= body + 2 else 0
    if level and len(text) < 200:
        para = document.add_heading(level=level)
    elif _LIST_MARK.match(text.split(" ", 1)[0]) and text.split(" ", 1)[0] in "•●▪◦■➢►-–*" and " " in text:
        para = document.add_paragraph(style="List Bullet")
        b["segs"][0][0] = b["segs"][0][0].lstrip()[1:].lstrip()
    else:
        para = document.add_paragraph()
    for seg_text, bold, italic, ssize in b["segs"]:
        if not seg_text:
            continue
        run = para.add_run(seg_text)
        if not level:
            run.bold = bold or None
        run.italic = italic or None
        if abs(ssize - body) >= 1 or level:
            run.font.size = Pt(round(ssize * 2) / 2)
    if b.get("center"):
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER


register(Tool(
    type="pdfToOfficeWord", slug="pdf-to-word", title="PDF to Word", icon="doc", category="from_pdf", popular=True,
    tagline="Convert a PDF into an editable Word document, keeping paragraphs, headings, tables and pictures.",
    handler=pdf_to_word, keywords="docx doc word editable convert",
))


# ---------------------------------------------------------------------------
# PDF -> PowerPoint


def pdf_to_ppt(ctx):
    from pptx import Presentation
    from pptx.util import Emu

    for inp in ctx.inputs:
        prs = Presentation()
        with pdfium_doc(inp) as doc:
            try:
                doc.init_forms()
            except Exception:
                pass
            w, h = doc[0].get_size()
            # PowerPoint allows slides between 1 and 56 inches
            k = min(1.0, 4032 / max(w, h))
            sw, sh = max(72, w * k), max(72, h * k)
            prs.slide_width, prs.slide_height = Emu(int(sw * 12700)), Emu(int(sh * 12700))
            blank = prs.slide_layouts[6]
            for i in range(len(doc)):
                ctx.check_cancelled()
                page = doc[i]
                pw, ph = page.get_size()
                scale = _safe_dpi(page, 144) / 72
                pil = page.render(scale=scale, draw_annots=True, may_draw_forms=True).to_pil().convert("RGB")
                buf = io.BytesIO()
                pil.save(buf, "JPEG", quality=88)
                buf.seek(0)
                slide = prs.slides.add_slide(blank)
                fit = min(sw / pw, sh / ph)  # keep the page's aspect ratio on the slide
                dw, dh = pw * fit, ph * fit
                slide.shapes.add_picture(buf, Emu(int((sw - dw) / 2 * 12700)), Emu(int((sh - dh) / 2 * 12700)),
                                         Emu(int(dw * 12700)), Emu(int(dh * 12700)))
                text = _page_text(page).strip()
                if text:
                    slide.notes_slide.notes_text_frame.text = text
        prs.save(ctx.output(f"{inp.stem}.pptx"))
    ctx.remark("Converted to PowerPoint (one slide per page; page text is in the speaker notes)")


register(Tool(
    type="pdfToPpt", slug="pdf-to-ppt", title="PDF to PowerPoint", icon="slides", category="from_pdf",
    tagline="Turn each PDF page into a PowerPoint slide.",
    handler=pdf_to_ppt, keywords="pptx powerpoint slides presentation convert",
))


# ---------------------------------------------------------------------------
# Word -> PDF


def doc_to_pdf(ctx):
    soffice = soffice_path()
    for inp in ctx.inputs:
        ctx.check_cancelled()
        engine_failed = False
        if soffice:
            # LibreOffice creates deeply nested profile files. Keep these paths
            # short on Windows (a task-id based path can exceed MAX_PATH).
            with tempfile.TemporaryDirectory(prefix="pdfnova-lo-") as work:
                root = Path(work)
                ext = Path(inp.name).suffix.lower() or ".docx"
                src = root / ("input" + ext)
                shutil.copyfile(inp.path, src)
                profile = root / "profile"
                outdir = root / "out"
                outdir.mkdir()
                cmd = [soffice, f"-env:UserInstallation={profile.resolve().as_uri()}", "--headless",
                       "--nologo", "--norestore", "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(src)]
                try:
                    _run(cmd, timeout=180)
                except subprocess.TimeoutExpired:
                    raise TaskError(f"Converting '{inp.name}' took too long") from None
                except (subprocess.SubprocessError, OSError):
                    engine_failed = True
                produced = outdir / "input.pdf"
                if not produced.exists() or produced.stat().st_size == 0:
                    engine_failed = True
                if not engine_failed:
                    shutil.move(produced, ctx.output(f"{inp.stem}.pdf"))
                    continue
        if inp.name.lower().endswith((".docx", ".txt")):
            try:
                _simple_docx_to_pdf(inp, ctx.output(f"{inp.stem}.pdf"))
            except TaskError:
                raise
            except Exception:
                raise TaskError(f"Could not read '{inp.name}'. It may be damaged or not a Word document.") from None
            reason = "LibreOffice failed on the server." if engine_failed else "LibreOffice is not installed on the server."
            ctx.warn(f"{reason} Converted with the basic built-in converter (text, tables and pictures only); layout may differ.")
        else:
            raise TaskError("Converting this file type needs LibreOffice on the server")
    ctx.remark("Converted to PDF")


def _simple_docx_to_pdf(inp, out: Path):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from .draw import unicode_font

    styles = getSampleStyleSheet()
    uni = unicode_font()
    if uni:
        for s in styles.byName.values():
            s.fontName = uni
    page_w, page_h = PAGE_SIZES_PT["a4"]
    frame_w = page_w - 112
    story = []
    header = footer = ""
    if inp.name.lower().endswith(".txt"):
        raw = inp.path.read_bytes()
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("cp1252", errors="replace")
        for line in content.splitlines():
            lead = len(line) - len(line.lstrip(" "))
            story.append(Paragraph("&nbsp;" * lead + escape(line.strip(" ")) or "&nbsp;", styles["Normal"]))
    else:
        from docx import Document
        from docx.table import Table as DT
        from docx.text.paragraph import Paragraph as DP

        d = Document(str(inp.path))
        try:
            sec = d.sections[0]
            header = " ".join(p.text for p in sec.header.paragraphs if p.text.strip())
            footer = " ".join(p.text for p in sec.footer.paragraphs if p.text.strip())
        except Exception:
            pass
        A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"

        def pictures(el):
            for drawing in el.iter(A.replace("main", "main") + "blip"):
                rid = drawing.get(R + "embed")
                part = d.part.related_parts.get(rid) if rid else None
                if part is None:
                    continue
                ext = None
                for anc in drawing.iterancestors():
                    ext = anc.find(WP + "extent")
                    if ext is not None:
                        break
                try:
                    w = int(ext.get("cx")) / 12700 if ext is not None else 200
                    h = int(ext.get("cy")) / 12700 if ext is not None else 150
                    k = min(1.0, frame_w / w, (page_h - 160) / h)
                    yield RLImage(io.BytesIO(part.blob), width=w * k, height=h * k)
                except Exception:
                    continue

        for child in d.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = DP(child, d)
                name = (p.style.name or "").lower() if p.style is not None else ""
                st = (styles["Title"] if name == "title" else styles["Heading1"] if name.startswith("heading 1")
                      else styles["Heading2"] if name.startswith("heading") else styles["Normal"])
                html = "".join(
                    (f"<b>{escape(r.text)}</b>" if r.bold else f"<i>{escape(r.text)}</i>" if r.italic else escape(r.text)) for r in p.runs)
                story.append(Paragraph(html or "&nbsp;", st))
                story += list(pictures(child))
            elif tag == "tbl":
                t = DT(child, d)
                data = [[Paragraph(escape(c.text), styles["Normal"]) for c in row.cells] for row in t.rows]
                if data:
                    tbl = Table(data)
                    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                    story += [tbl, Spacer(1, 8)]

    def decorate(canvas, _doc):
        canvas.saveState()
        canvas.setFont(uni or "Helvetica", 9)
        if header:
            canvas.drawString(56, page_h - 36, header[:150])
        if footer:
            canvas.drawString(56, 30, footer[:150])
        canvas.restoreState()

    SimpleDocTemplate(str(out), pagesize=(page_w, page_h), leftMargin=56, rightMargin=56, topMargin=56,
                      bottomMargin=56).build(story or [Spacer(1, 1)], onFirstPage=decorate, onLaterPages=decorate)


register(Tool(
    type="docToPdf", slug="word-to-pdf", title="Word to PDF", icon="doc", category="to_pdf", popular=True,
    tagline="Convert Word documents (DOC, DOCX, ODT, RTF) into PDF.",
    handler=doc_to_pdf, accept=["doc", "docx", "odt", "rtf", "txt"], keywords="docx doc word convert",
    requires="LibreOffice (for exact layout)",
))


# ---------------------------------------------------------------------------
# HTML -> PDF

_PAPER_WIDTH_IN = {"A4": 8.27, "A3": 11.69, "A2": 16.54, "Letter": 8.5, "Legal": 8.5, "Tabloid": 11}
_PAPER_HEIGHT_IN = {"A4": 11.69, "A3": 16.54, "A2": 23.39, "Letter": 11, "Legal": 14, "Tabloid": 17}
_UNIT_PX = {"px": 1, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4}
_AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "googleadservices.com", "adnxs.com", "adsrvr.org")


def _fetch_html_resource(request, *, transport=None, max_bytes=30 * 1024 * 1024):
    """Fetch browser resources with every redirect checked and IP-pinned.

    Chromium must never independently resolve an untrusted hostname. Decode bodies
    before fulfilling and remove the corresponding wire-encoding headers.
    """
    excluded = {"host", "connection", "content-length", "accept-encoding", "proxy-authorization"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded}
    end = time.monotonic() + 30
    url, method, content = request.url, request.method, request.post_data_buffer
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, transport=transport) as client:
        for _ in range(6):
            if time.monotonic() > end:
                raise UnsafeUrl("The page resource took too long")
            target, pinned_headers, extensions = _pinned(url, resolve_public(url)[0])
            with client.stream(method, target, headers={**headers, **pinned_headers}, extensions=extensions,
                               content=content) as response:
                if response.is_redirect and response.headers.get("location"):
                    next_url = urljoin(url, response.headers["location"])
                    old_origin, new_origin = urlparse(url), urlparse(next_url)
                    if (new_origin.scheme, new_origin.netloc) != (old_origin.scheme, old_origin.netloc):
                        headers = {k: v for k, v in headers.items() if k.lower() not in ("authorization", "cookie")}
                    if response.status_code == 303 or (response.status_code in (301, 302) and method == "POST"):
                        method, content = "GET", None
                    url = next_url
                    continue
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > max_bytes or time.monotonic() > end:
                        raise UnsafeUrl("The page resource is too large or took too long")
                    body.extend(chunk)
                excluded_response = {"content-length", "content-encoding", "transfer-encoding", "connection", "x-pdfnova-final-url"}
                response_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded_response}
                if url != request.url:
                    response_headers["x-pdfnova-final-url"] = url
                return response.status_code, response_headers, bytes(body)
    raise UnsafeUrl("Too many page redirects")


def _redirected_resource(body, headers, resource_type, final_url):
    """Preserve document/CSS relative URLs when redirects are followed off-browser."""
    content_type = headers.get("content-type", "").lower()
    if resource_type == "document" and ("html" in content_type or not content_type):
        # ASCII insertion preserves the page's original byte encoding.
        base = re.search(br"<base\b[^>]*\bhref\s*=\s*(?:[\"']([^\"']*)[\"']|([^\s>]+))", body, re.I)
        href = final_url
        if base:
            href = urljoin(final_url, html_lib.unescape((base[1] or base[2]).decode("utf-8", errors="replace")))
        tag = ('<base href="' + html_lib.escape(href, quote=True) + '">').encode("ascii", errors="xmlcharrefreplace")
        head = re.search(br"<head\b[^>]*>", body, re.I)
        offset = head.end() if head else 0
        return body[:offset] + tag + body[offset:]
    if resource_type == "stylesheet" or "text/css" in content_type:
        # Rewrite relative URLs in redirected CSS, including imported sheets.
        def absolute(match):
            value = match[2].strip().strip(b"\"'")
            url = urljoin(final_url, value.decode("utf-8", errors="replace"))
            return match[1] + ('"' + url.replace('"', '%22') + '"').encode() + match[3]
        body = re.sub(br"(url\(\s*)([^)]+)(\s*\))", absolute, body, flags=re.I)
        body = re.sub(br"(@import\s+)([\"'][^\"']+[\"'])(\s*[; ])", absolute, body, flags=re.I)
    return body


def html_to_pdf(ctx):
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise TaskError("HTML to PDF needs Chromium on the server (pip install playwright && playwright install chromium)") from None
    urls = [u.strip() for u in re.split(r"[\n,]+", ctx.param("urls") or "") if u.strip()]
    html_code = ctx.param("htmlCode") or ""
    locale = str(ctx.param("lang") or "en-US").replace("_", "-")
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale):
        raise TaskError("Enter a valid browser language, such as en-US or hi-IN")
    timezone = str(ctx.param("timezone") or "UTC")
    partial = ctx.flag("partialContentAllowed", True)
    header_footer = ctx.flag("includeHeaderFooterDetails")
    resource_errors = []
    prefetched_resources = {}
    html_files = [i for i in ctx.inputs if i.name.lower().endswith((".html", ".htm"))]
    if not urls and not html_code and not html_files:
        raise TaskError("Enter a web address or some HTML")
    if len(urls) > 20:
        raise TaskError("Enter at most 20 web addresses at a time")
    for i, u in enumerate(urls):
        if "://" not in u:
            urls[i] = u = "https://" + u
        try:
            _check_host(u)
        except UnsafeUrl as e:
            raise TaskError(f"{u}: {e}") from None
    size = ctx.param("pageSize", "A4")
    size = next((k for k in _PAPER_WIDTH_IN if k.lower() == str(size).lower()), "A4")
    landscape = ctx.param("pageOrientation", "portrait") == "landscape"
    unit = ctx.param("pageMarginUnits", "px")
    unit = unit if unit in _UNIT_PX else "px"
    margin_val = max(0.0, _num(ctx.param("pageMargin"), 0))
    margin_px = margin_val * _UNIT_PX[unit]
    if header_footer:
        # Leave room for Chromium's date/title/URL/page-number print details.
        margin_px = max(margin_px, 40)
        margin_val, unit = margin_px, "px"
    paper_px = (_PAPER_HEIGHT_IN if landscape else _PAPER_WIDTH_IN)[size] * 96
    if margin_px * 2 > paper_px * 0.8:
        raise TaskError("The page margin is too large for this page size")
    margin = f"{margin_val}{unit}"
    delay = min(5, max(0, int(_num(ctx.param("delay"), 0)))) * 1000
    viewport = max(320, min(int(_num(ctx.param("viewportWidth"), 1280) or 1280), 3840))
    # lay the page out at the browser width, then scale it onto the paper (like a desktop "print to fit")
    scale = max(0.1, min(2.0, (paper_px - 2 * margin_px) / viewport))
    media = "print" if ctx.flag("usePrintMedia") else "screen"

    def guard(route):
        url = route.request.url
        scheme = url.split(":", 1)[0].lower()
        if scheme in ("data", "blob", "about"):
            return route.continue_()
        if scheme not in ("http", "https") or route.request.resource_type in ("media", "websocket"):
            return route.abort("blockedbyclient")
        host = (urlparse(url).hostname or "").lower()
        if ctx.flag("blockAds") and any(host == ad or host.endswith("." + ad) for ad in _AD_HOSTS):
            return route.abort("blockedbyclient")
        try:
            prefetched = prefetched_resources.pop(url, None)
            status, headers, body = prefetched if prefetched is not None else _fetch_html_resource(route.request)
        except (UnsafeUrl, httpx.HTTPError, ValueError):
            resource_errors.append(url)
            return route.abort("failed")
        final_url = headers.pop("x-pdfnova-final-url", None)
        if final_url:
            body = _redirected_resource(body, headers, route.request.resource_type, final_url)
        route.fulfill(status=status, headers=headers, body=body)

    def ws_guard(ws):
        # Sockets cannot use the pinned HTTP path, so never connect them.
        # A virtual peer discards messages. close() can deadlock during page load
        # on some Chromium versions; never calling connect_to_server is the gate.
        ws.on_message(lambda message: None)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                                          "--disable-features=DnsOverHttps"])
        try:
            try:
                context = browser.new_context(viewport={"width": viewport, "height": 900}, service_workers="block",
                                              accept_downloads=False, locale=locale, timezone_id=timezone)
            except PlaywrightError:
                raise TaskError("Could not configure the browser; check the language and IANA timezone") from None
            context.route("**/*", guard)
            try:
                context.route_web_socket(re.compile(".*"), ws_guard)
            except AttributeError:
                raise TaskError("HTML conversion needs Playwright 1.48 or newer to safely block WebSockets") from None
            jobs = [(u, None) for u in urls]
            if html_code:
                jobs.append((None, html_code))
            jobs += [(None, f.path.read_text(encoding="utf-8", errors="replace")) for f in html_files]
            for n, (url, html) in enumerate(jobs, 1):
                ctx.check_cancelled()
                resource_errors.clear()
                page = None
                try:
                    page = context.new_page()
                    if url:
                        # Browser routing skips HTTP redirect follow-ups. Resolve
                        # the chain safely first, then navigate to its final URL
                        # so origin, CSP, scripts and relative URLs stay correct.
                        try:
                            status, headers, body = _fetch_html_resource(SimpleNamespace(
                                url=url, method="GET", post_data_buffer=None,
                                headers={"user-agent": page.evaluate("navigator.userAgent"), "accept-language": locale}))
                        except (UnsafeUrl, httpx.HTTPError, ValueError):
                            raise TaskError(f"Could not load {url} safely") from None
                        navigation_url = headers.pop("x-pdfnova-final-url", url)
                        prefetched_resources[navigation_url] = (status, headers, body)
                        try:
                            page.goto(navigation_url, wait_until="load", timeout=60000)
                        except PlaywrightTimeout:
                            if not partial:
                                raise
                            ctx.warn("The page did not finish loading; the available content was saved.")
                        name = re.sub(r"[^\w.-]+", "_", url.split("://", 1)[1]).strip("_")[:80] or f"page-{n}"
                    else:
                        try:
                            page.set_content(html, wait_until="load", timeout=60000)
                        except PlaywrightTimeout:
                            if not partial:
                                raise
                            ctx.warn("The HTML did not finish loading; the available content was saved.")
                        name = f"page-{n}"
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightError:
                        pass  # pages that keep polling never go idle; print what we have
                    _scroll_through(page)
                    if delay:
                        page.wait_for_timeout(delay)
                    if ctx.flag("hideNotices"):
                        page.evaluate("""() => {
                            for (const element of document.querySelectorAll('#onetrust-banner-sdk, #onetrust-consent-sdk, #CybotCookiebotDialog, #cookie-notice, #cookie-banner, .cookie-banner, .cookie-notice, .cc-window')) {
                                element.style.setProperty('display', 'none', 'important');
                            }
                        }""")
                    if resource_errors:
                        if not partial:
                            raise TaskError("Some page resources could not be loaded safely. Enable partial content to save the available page.")
                        ctx.warn("Some page resources could not be loaded safely; the available content was saved.")
                    page.emulate_media(media=media)
                    page.pdf(path=str(ctx.output(name + ".pdf")), format=size, landscape=landscape, print_background=True,
                             scale=scale, display_header_footer=header_footer,
                             margin={"top": margin, "bottom": margin, "left": margin, "right": margin})
                except PlaywrightError as e:
                    msg = str(e).splitlines()[0]
                    reason = re.search(r"net::(ERR_[A-Z_]+)", msg)
                    raise TaskError(f"Could not open {url or 'the HTML'}"
                                    f"{' (' + reason.group(1) + ')' if reason else ''}") from None
                finally:
                    prefetched_resources.clear()
                    if page is not None:
                        page.close()
        finally:
            browser.close()
    ctx.remark("Converted to PDF")


def _scroll_through(page):
    """Scroll to the bottom and back so lazy-loaded pictures appear (bounded)."""
    try:
        page.evaluate("""async () => {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            let y = 0;
            for (let i = 0; i < 40 && y < document.body.scrollHeight; i++) {
                y += window.innerHeight; window.scrollTo(0, y); await sleep(80);
            }
            window.scrollTo(0, 0);
        }""")
        page.wait_for_timeout(200)
    except Exception:
        pass


register(Tool(
    type="htmlToPdf", slug="html-to-pdf", title="HTML to PDF", icon="globe", category="to_pdf",
    tagline="Save web pages or HTML code as PDF documents.",
    handler=html_to_pdf, accept=["html", "htm"], min_files=0, keywords="web page website url save print",
    requires="Chromium via Playwright",
    options=[
        Opt("urls", "Web addresses (one per line)", "textarea", placeholder="https://example.com"),
        Opt("htmlCode", "…or paste HTML", "textarea", placeholder="<h1>Hello</h1>", advanced=True),
        Opt("pageSize", "Page size", "select", [("A4", "A4"), ("Letter", "Letter"), ("Legal", "Legal"), ("A3", "A3"), ("A2", "A2")], "A4"),
        Opt("pageOrientation", "Orientation", "radio", [("portrait", "Portrait"), ("landscape", "Landscape")], "portrait"),
        Opt("viewportWidth", "Browser width (px)", "number", default=1280, min=320, max=3840, advanced=True),
        Opt("pageMargin", "Margin", "number", default=0, min=0, advanced=True),
        Opt("pageMarginUnits", "Margin unit", "radio", [("px", "px"), ("mm", "mm"), ("cm", "cm"), ("in", "in")], "px", advanced=True),
        Opt("delay", "Wait before saving (seconds)", "select", [(str(i), str(i)) for i in range(6)], "0", advanced=True),
        Opt("usePrintMedia", "Use the page's print styles", "checkbox", advanced=True),
        Opt("lang", "Browser language", default="en-US", placeholder="en-US, hi-IN, fr", advanced=True),
        Opt("timezone", "Browser timezone", default="UTC", placeholder="Asia/Kolkata", advanced=True),
        Opt("includeHeaderFooterDetails", "Include date, title, URL and page numbers", "checkbox", advanced=True),
        Opt("hideNotices", "Hide common cookie banners", "checkbox", help="Hides known banner selectors; some sites require manual handling.", advanced=True),
        Opt("blockAds", "Block common advertising domains", "checkbox", help="Uses a small built-in domain list; some ads may remain.", advanced=True),
        Opt("partialContentAllowed", "Save available content if some resources fail", "checkbox", default=True, advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# OCR

LANG_NAMES = {
    "eng": "English", "hin": "Hindi", "spa": "Spanish", "fra": "French", "deu": "German", "ita": "Italian",
    "por": "Portuguese", "nld": "Dutch", "rus": "Russian", "ara": "Arabic", "chi_sim": "Chinese (simplified)",
    "chi_tra": "Chinese (traditional)", "jpn": "Japanese", "kor": "Korean", "tur": "Turkish", "pol": "Polish",
    "ben": "Bengali", "tam": "Tamil", "tel": "Telugu", "mar": "Marathi", "guj": "Gujarati", "urd": "Urdu",
    "kan": "Kannada", "mal": "Malayalam", "pan": "Punjabi", "nep": "Nepali", "ukr": "Ukrainian", "ces": "Czech",
    "swe": "Swedish", "dan": "Danish", "nor": "Norwegian", "fin": "Finnish", "ell": "Greek", "heb": "Hebrew",
    "hun": "Hungarian", "ron": "Romanian", "bul": "Bulgarian", "hrv": "Croatian", "srp": "Serbian", "slk": "Slovak",
    "slv": "Slovenian", "vie": "Vietnamese", "tha": "Thai", "ind": "Indonesian", "msa": "Malay", "fil": "Filipino",
    "fas": "Persian", "cat": "Catalan", "lat": "Latin", "san": "Sanskrit",
}
# kept for backwards compatibility (the full list the UI used to show)
OCR_LANGS = [(c, LANG_NAMES[c]) for c in ("eng", "hin", "spa", "fra", "deu", "ita", "por", "nld", "rus", "ara", "chi_sim",
                                          "jpn", "kor", "tur", "pol", "ben", "tam", "tel", "mar", "guj", "urd")]


@functools.lru_cache(maxsize=1)
def installed_ocr_langs() -> tuple[str, ...]:
    """Language packs Tesseract can load (honours TESSDATA_PREFIX)."""
    tess = tesseract_path()
    if not tess:
        return ()
    try:
        out = subprocess.run([tess, "--list-langs"], capture_output=True, timeout=20).stdout.decode(errors="replace")
    except (subprocess.SubprocessError, OSError):
        return ()
    langs = [ln.strip() for ln in out.splitlines()[1:] if re.fullmatch(r"[A-Za-z_]+", ln.strip() or "-")]
    return tuple(sorted({l for l in langs if l not in ("osd", "equ", "snum")}, key=lambda c: (c != "eng", LANG_NAMES.get(c, c))))


def _ocr_lang_choices():
    langs = installed_ocr_langs() or ("eng",)
    return [(c, LANG_NAMES.get(c, c)) for c in langs]


def ocr(ctx):
    from .draw import draw_form, invert, mul, user_to_visible, visible_size

    tess = tesseract_path()
    if not tess:
        raise TaskError("OCR needs Tesseract on the server (apt install tesseract-ocr)")
    raw_lang = str(ctx.param("lang") or "eng")
    langs = [l for l in re.split(r"[+,\s]+", raw_lang) if re.fullmatch(r"[A-Za-z_]{2,20}", l)][:4] or ["eng"]
    lang = "+".join(langs)
    installed = installed_ocr_langs()
    missing = [l for l in langs if installed and l not in installed]
    if missing:
        names = ", ".join(LANG_NAMES.get(l, l) for l in installed)
        raise TaskError(f"The OCR language '{LANG_NAMES.get(missing[0], missing[0])}' is not installed on the server. "
                        f"Available: {names}")
    formats = ctx.params.get("outputFormats") or ["pdf"]
    formats = [formats] if isinstance(formats, str) else formats
    formats = [f for f in formats if f in ("pdf", "txt")] or ["pdf"]
    psm = "1" if "osd" in _tess_all_langs() else "3"  # 1 = detect page orientation (sideways scans)
    skipped = 0
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        texts = []
        with pdfium_doc(inp) as doc:
            sel = pages_or_error(ctx.param("pages"), len(doc))
            for p in sel:
                ctx.check_cancelled()
                existing = _page_text(doc[p - 1]) if "txt" in formats else ""
                if _has_text(doc[p - 1]):
                    skipped += 1
                    texts.append(existing or _page_text(doc[p - 1]))
                    continue
                dpi = _safe_dpi(doc[p - 1], 300)
                img = ctx.temp(f"p{p}.png")
                doc[p - 1].render(scale=dpi / 72, may_draw_forms=False).to_pil().convert("L").save(img, dpi=(dpi, dpi))
                base = ctx.temp(f"p{p}")
                try:
                    _run([tess, str(img), str(base), "-l", lang, "--psm", psm, "--dpi", str(round(dpi)),
                          "-c", "textonly_pdf=1", "pdf", "txt"], timeout=300)
                except subprocess.CalledProcessError as e:
                    msg = (e.stderr or b"").decode(errors="replace")
                    if "Failed loading language" in msg or "Error opening data file" in msg:
                        raise TaskError(f"The OCR language '{lang}' is not installed on the server") from None
                    raise TaskError("OCR failed on page %d" % p) from None
                except (subprocess.SubprocessError, OSError):
                    raise TaskError("OCR failed on page %d" % p) from None
                texts.append(Path(str(base) + ".txt").read_text(encoding="utf-8", errors="replace"))
                with pikepdf.open(str(base) + ".pdf") as layer:
                    lp = pdf.copy_foreign(layer.pages[0].obj)
                    form = pikepdf.Page(lp).as_form_xobject()
                    lw, lh = (float(v) for v in layer.pages[0].mediabox[2:])
                page = pdf.pages[p - 1]
                vw, vh = visible_size(page)
                m = (vw / lw, 0, 0, vh / lh, 0, 0)
                draw_form(pdf, page, form, mul(m, invert(user_to_visible(page))))
        if "pdf" in formats:
            pdf.save(ctx.output(output_name(ctx, inp)))
        if "txt" in formats:
            ctx.output(f"{inp.stem}.txt").write_text("\n\f".join(t.strip("\n") + "\n" for t in texts), encoding="utf-8", newline="\n")
    if skipped:
        ctx.warn(f"{skipped} page{'s' if skipped != 1 else ''} already had selectable text and "
                 f"{'were' if skipped != 1 else 'was'} left as {'they were' if skipped != 1 else 'it was'}.")
    ctx.remark("Text recognized — the PDF is now searchable")


@functools.lru_cache(maxsize=1)
def _tess_all_langs() -> tuple[str, ...]:
    tess = tesseract_path()
    if not tess:
        return ()
    try:
        out = subprocess.run([tess, "--list-langs"], capture_output=True, timeout=20).stdout.decode(errors="replace")
    except (subprocess.SubprocessError, OSError):
        return ()
    return tuple(ln.strip() for ln in out.splitlines()[1:])


def _has_text(page) -> bool:
    """A page with real (non-whitespace) text already – OCR would only duplicate it."""
    tp = page.get_textpage()
    try:
        text = tp.get_text_range()
    finally:
        tp.close()
    return len(re.sub(r"\s+", "", text)) >= 20


register(Tool(
    type="ocr", slug="ocr-pdf", title="OCR PDF", icon="scan", category="optimize",
    tagline="Recognize the text in scanned PDFs so you can search, select and copy it.",
    handler=ocr, keywords="scan recognize searchable text tesseract",
    requires="Tesseract OCR",
    extra_categories=["from_pdf"],
    options=[
        Opt("lang", "Document language", "select", _ocr_lang_choices(), "eng"),
        Opt("outputFormats", "Output", "radio", [("pdf", "Searchable PDF"), ("txt", "Text file")], "pdf"),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))
