"""Images -> PDF pages (used by merge, alternate mix and JPG to PDF)."""
from __future__ import annotations

import io
from pathlib import Path

import pikepdf
from PIL import Image, ImageOps

from ..jobs import TaskError
from .common import PAGE_SIZES_PT

IMAGE_EXTS = {"png", "gif", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}


def is_image(name: str, path: Path | None = None) -> bool:
    if name.rsplit(".", 1)[-1].lower() in IMAGE_EXTS:
        return True
    if path is not None:
        with open(path, "rb") as fh:
            return b"%PDF" not in fh.read(1024)
    return False


def _frames(path: Path):
    try:
        im = Image.open(path)
    except Exception:
        raise TaskError(f"Could not read image '{path.name}'") from None
    i = 0
    while True:
        try:
            im.seek(i)
        except EOFError:
            break
        frame = ImageOps.exif_transpose(im.copy())
        yield frame
        i += 1
        if getattr(im, "n_frames", 1) <= i:
            break


def image_to_pdf(path: Path, page_size: str = "auto", orientation: str = "auto", margin_pt: float = 0,
                 custom: tuple[float, float] | None = None, rotate: int = 0) -> pikepdf.Pdf:
    """Return a new PDF with one page per image frame.

    page_size "auto" makes the page the size of the image at 96 dpi; a named size
    (a4, letter, …) or "custom" fits the image inside with the margin.
    """
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = None
    for frame in _frames(path):
        if rotate % 360:
            frame = frame.rotate(-rotate, expand=True)
        if frame.mode in ("P", "LA", "RGBA", "PA") or (frame.mode == "I;16"):
            bg = Image.new("RGB", frame.size, "white")
            rgba = frame.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            frame = bg
        elif frame.mode not in ("RGB", "L", "CMYK", "1"):
            frame = frame.convert("RGB")
        dpi = frame.info.get("dpi", (96, 96))[0] or 96
        dpi = dpi if 30 <= dpi <= 1200 else 96
        iw, ih = frame.size[0] * 72 / dpi, frame.size[1] * 72 / dpi
        size = page_size.lower() if page_size else "auto"
        if size == "auto":
            pw, ph = iw + 2 * margin_pt, ih + 2 * margin_pt
        elif size == "custom" and custom:
            pw, ph = custom
        else:
            pw, ph = PAGE_SIZES_PT.get(size, PAGE_SIZES_PT["a4"])
        if size != "auto":
            landscape = iw > ih if orientation == "auto" else orientation == "landscape"
            if landscape != (pw > ph):
                pw, ph = ph, pw
        if c is None:
            c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
        else:
            c.setPageSize((pw, ph))
        aw, ah = max(pw - 2 * margin_pt, 1), max(ph - 2 * margin_pt, 1)
        scale = min(aw / iw, ah / ih, 1.0 if size == "auto" else 10**6)
        dw, dh = iw * scale, ih * scale
        img_buf = io.BytesIO()
        if frame.mode == "1":
            frame = frame.convert("L")
        fmt = "JPEG" if path.suffix.lower() in (".jpg", ".jpeg") and frame.mode in ("RGB", "L", "CMYK") else "PNG"
        frame.save(img_buf, format=fmt, quality=92)
        img_buf.seek(0)
        c.drawImage(ImageReader(img_buf), (pw - dw) / 2, (ph - dh) / 2, dw, dh)
        c.showPage()
    if c is None:
        raise TaskError(f"Image '{path.name}' has no frames")
    c.save()
    return pikepdf.open(io.BytesIO(buf.getvalue()))
