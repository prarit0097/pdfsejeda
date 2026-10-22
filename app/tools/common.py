"""Shared helpers for tool handlers: opening PDFs, saving, page sizes, units."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

import pikepdf

from ..jobs import InputFile, TaskError
from ..pages import PageSelectionError, parse_pages

PAGE_SIZES_PT = {  # width, height in points (portrait)
    "a0": (2384, 3370), "a1": (1684, 2384), "a2": (1191, 1684), "a3": (842, 1191), "a4": (595, 842),
    "a5": (420, 595), "a6": (298, 420), "letter": (612, 792), "legal": (612, 1008),
    "ledger": (1224, 792), "legder": (1224, 792), "tabloid": (792, 1224), "executive": (522, 756),
}

# PDFium is not thread-safe, even for different documents. Keep all native
# handles inside this reentrant scope; document.close() also closes its children.
PDFIUM_LOCK = threading.RLock()

UNIT_PT = {"inch": 72.0, "in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4, "pt": 1.0, "px": 0.75}


def open_pdf(inp: InputFile, allow_overwriting_input: bool = False) -> pikepdf.Pdf:
    try:
        return pikepdf.open(inp.path, password=inp.password or "", allow_overwriting_input=allow_overwriting_input)
    except pikepdf.PasswordError:
        raise TaskError(f"'{inp.name}' is password protected. Enter its password and try again.") from None
    except pikepdf.PdfError as e:
        raise TaskError(f"'{inp.name}' could not be read as a PDF ({_short(e)}). Try the Repair tool.") from None


def save_pdf(pdf: pikepdf.Pdf, path: Path, linearize: bool = False, compress: bool = True) -> Path:
    pdf.save(
        path,
        compress_streams=compress,
        object_stream_mode=pikepdf.ObjectStreamMode.generate if compress else pikepdf.ObjectStreamMode.preserve,
        linearize=linearize,
    )
    return path


def pages_or_error(spec, total: int, default_all: bool = True) -> list[int]:
    try:
        return parse_pages(spec, total, default_all)
    except PageSelectionError as e:
        raise TaskError(str(e)) from None


def require_pdfs(ctx) -> None:
    for inp in ctx.inputs:
        with open(inp.path, "rb") as fh:
            head = fh.read(1024)
        if b"%PDF" not in head:
            raise TaskError(f"'{inp.name}' is not a PDF file")


def page_box(page: pikepdf.Page) -> tuple[float, float, float, float]:
    """Visible box (CropBox falling back to MediaBox) as floats x0,y0,x1,y1."""
    box = page.obj.get("/CropBox", None) or page.mediabox
    x0, y0, x1, y1 = (float(v) for v in box)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def rotation(page: pikepdf.Page) -> int:
    return int(page.obj.get("/Rotate", 0)) % 360


def output_name(ctx, inp: InputFile, suffix: str = "", ext: str = ".pdf") -> str:
    """Honour outputFilenamePattern ([BASENAME], [TIMESTAMP]) or default to the input name."""
    pattern = (ctx.param("outputFilenamePattern") or "").strip()
    if pattern:
        import time

        name = pattern.replace("[BASENAME]", inp.stem).replace("[TIMESTAMP]", time.strftime("%Y%m%d%H%M%S"))
        return name if name.lower().endswith(ext) else name + ext
    return f"{inp.stem}{suffix}{ext}"


@contextmanager
def pdfium_doc(inp: InputFile):
    """Open, use and close PDFium under one process-wide native-library lock.

    Do not use retained document/page/text/bitmap handles outside this scope.
    PIL/NumPy data backed by the default native bitmap buffers may outlive it.
    """
    with PDFIUM_LOCK:
        import pypdfium2 as pdfium

        try:
            doc = pdfium.PdfDocument(str(inp.path), password=inp.password or None)
        except pdfium.PdfiumError as e:
            if "password" in str(e).lower():
                raise TaskError(f"'{inp.name}' is password protected. Enter its password and try again.") from None
            raise TaskError(f"'{inp.name}' could not be rendered ({_short(e)})") from None
        try:
            yield doc
        finally:
            doc.close()


def _short(e: Exception) -> str:
    s = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return s[:120]
