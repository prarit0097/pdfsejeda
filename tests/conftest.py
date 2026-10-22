"""Test fixtures: an isolated DATA_DIR, sample PDFs made with reportlab, and a
helper that runs a tool handler synchronously and returns its outputs."""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="pdfnova-test-"))
os.environ.setdefault("ALLOW_PRIVATE_URLS", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pikepdf  # noqa: E402
import pytest  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.jobs import InputFile, Task, TaskContext, queue  # noqa: E402
from app.storage import files  # noqa: E402


def make_pdf(pages: int = 3, size=A4, title: str = "Sample", bookmarks: bool = False, texts=None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    c.setTitle(title)
    for i in range(pages):
        w, h = size
        c.setFont("Helvetica", 24)
        text = texts[i] if texts else f"Page {i + 1}"
        c.drawString(72, h - 72, text)
        c.setFont("Helvetica", 11)
        c.drawString(72, h - 110, "The quick brown fox jumps over the lazy dog.")
        c.rect(60, 60, w - 120, 80)
        if bookmarks:
            key = f"p{i}"
            c.bookmarkPage(key)
            c.addOutlineEntry(f"Chapter {i + 1}", key, level=0)
        c.showPage()
    c.save()
    return buf.getvalue()


def make_png(w=200, h=100, color=(200, 30, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def store(data: bytes, name: str = "doc.pdf", mime: str = "application/pdf"):
    return files.save_bytes(name, data, mime)


def run_tool(task_type: str, inputs: list, **params):
    """Run a tool handler inline. `inputs` are StoredFile objects. Returns (task, {name: bytes})."""
    from app.tools.registry import get_tool

    tool = get_tool(task_type)
    tool.validate(inputs, params)
    task = Task(id=f"TEST{os.urandom(3).hex().upper()}-202601010000", type=task_type, params=params,
                file_ids=[f.id for f in inputs])
    ctx = TaskContext(task, [InputFile(f.id, f.name, f.path, f.password) for f in inputs])
    tool.handler(ctx)
    queue._finish(task)
    out = {p.name: p.read_bytes() for p in task.out_dir.iterdir() if p.is_file()}
    return task, out


def open_out(data: bytes) -> pikepdf.Pdf:
    return pikepdf.open(io.BytesIO(data))


@pytest.fixture
def pdf3():
    return store(make_pdf(3), "three.pdf")


@pytest.fixture
def pdf_landscape():
    return store(make_pdf(2, landscape(A4)), "wide.pdf")
