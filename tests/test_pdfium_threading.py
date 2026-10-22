"""Native PDFium operations must serialize across independent worker tasks."""
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pypdf
import pypdfium2 as pdfium
import pytest

from app.jobs import TaskError
from app.tools import common, modify
from conftest import run_tool, store


def test_actual_rendering_tasks_serialize_document_lifetimes(monkeypatch, pdf3):
    first_rendered = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_opened = threading.Event()
    counter_lock = threading.Lock()
    attempts = 0
    opens = 0
    original_scope = modify.pdfium_doc
    original_open = pdfium.PdfDocument
    original_bbox = modify._content_bbox

    @contextmanager
    def tracked_scope(inp):
        nonlocal attempts
        with counter_lock:
            attempts += 1
            if attempts == 2:
                second_attempted.set()
        with original_scope(inp) as doc:
            yield doc

    def tracked_open(*args, **kwargs):
        nonlocal opens
        with counter_lock:
            opens += 1
            if opens == 2:
                second_opened.set()
        return original_open(*args, **kwargs)

    def held_after_actual_render(doc, index, *args, **kwargs):
        result = original_bbox(doc, index, *args, **kwargs)
        if not first_rendered.is_set():
            first_rendered.set()
            assert release_first.wait(5)
        return result

    monkeypatch.setattr(modify, "pdfium_doc", tracked_scope)
    monkeypatch.setattr(pdfium, "PdfDocument", tracked_open)
    monkeypatch.setattr(modify, "_content_bbox", held_after_actual_render)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_tool, "crop", [pdf3], cropMode="auto")
        try:
            assert first_rendered.wait(3)
            second = pool.submit(run_tool, "crop", [pdf3], cropMode="auto")
            assert second_attempted.wait(3)
            # The second task reached the helper, but cannot even open its
            # independent document until the first rendering scope is closed.
            assert not second_opened.wait(0.15)
        finally:
            release_first.set()
        results = [first.result(timeout=5), second.result(timeout=5)]
    assert second_opened.is_set()
    for _, output in results:
        reader = pypdf.PdfReader(io.BytesIO(next(iter(output.values()))))
        assert len(reader.pages) == 3
        assert all(10 < float(page.mediabox.width) < 596 for page in reader.pages)


def test_pdfium_scope_releases_lock_after_open_and_body_errors(pdf3):
    broken = store(b"not a PDF", "broken.pdf")
    with pytest.raises(TaskError, match="could not be rendered"):
        with common.pdfium_doc(broken):
            pass
    with pytest.raises(RuntimeError, match="interrupted"):
        with common.pdfium_doc(pdf3):
            raise RuntimeError("interrupted")
    with ThreadPoolExecutor(max_workers=1) as pool:
        def render():
            with common.pdfium_doc(pdf3) as doc:
                page = doc[0]
                bitmap = page.render(scale=0.2)
                result = bitmap.width, bitmap.height
                bitmap.close()
                return result
        width, height = pool.submit(render).result(timeout=3)
    assert width > 0 and height > 0
