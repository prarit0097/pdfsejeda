"""Real Chromium checks for every tool page and representative upload-to-download flows.

Run a local server, then: python scripts/browser_regression.py http://127.0.0.1:8000
Install the optional test browser with: pip install playwright; playwright install chromium
Results/screenshots go to an ignored data-qa-browser directory; no external PDF service is used.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import httpx
import pikepdf
from playwright.sync_api import sync_playwright
from reportlab.pdfgen import canvas

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
OUT = Path("data-qa-browser")


def sample_pdf():
    b = io.BytesIO()
    c = canvas.Canvas(b)
    c.setTitle("Browser fixture")
    for i in range(3):
        c.drawString(72, 740, f"Browser page {i + 1}")
        c.bookmarkPage(f"p{i}")
        c.addOutlineEntry(f"Chapter {i+1}", f"p{i}")
        c.showPage()
    c.save()
    return b.getvalue()


def main():
    OUT.mkdir(exist_ok=True)
    results = []
    with httpx.Client(base_url=BASE, timeout=30) as api, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1365, "height": 900}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def check(name, fn):
            errors.clear()
            started = time.monotonic()
            try:
                fn()
                assert not errors, f"Browser errors: {errors}"
                results.append({"name": name, "ok": True, "seconds": round(time.monotonic()-started, 2)})
                print(f"PASS {name}", flush=True)
            except Exception as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                page.screenshot(path=str(OUT / (str(len(results)) + "-failure.png")), full_page=True)
                print(f"FAIL {name}: {e}", flush=True)

        def load(slug):
            response = page.goto(BASE + "/" + slug, wait_until="load")
            assert response.status == 200
            page.wait_for_function("() => window.UI !== undefined")

        def shell(slug):
            load(slug)
            assert page.locator("h1").count() == 1
            page.get_by_role("button", name="All tools", exact=True).click()
            assert page.locator("#mega").is_visible()
            page.keyboard.press("Escape")
            assert page.locator("#mega").is_hidden()
            if page.locator("#tool-config").count():
                page.wait_for_function("() => window.Tool !== undefined")

        def home():
            load("")
            page.locator("#tool-search").fill("compress")
            assert page.locator(".tool-card:visible").count() >= 1
            assert page.locator(".tool-card:visible").filter(has_text="Compress PDF").count() >= 1
            page.locator("#tool-search").fill("zzzznoresult")
            assert page.locator("#no-results").is_visible()
            page.locator("#theme-btn").click()
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.reload(wait_until="load")
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.screenshot(path=str(OUT / "home-desktop.png"), full_page=True)

        def upload(slug, count=1):
            load(slug)
            page.locator("#file-input").set_input_files([
                {"name": f"browser-{i}.pdf", "mimeType": "application/pdf", "buffer": sample_pdf()}
                for i in range(count)
            ])
            page.wait_for_function("count => Tool.readyFiles().length === count", arg=count)
            page.locator("#task-form").wait_for(state="visible")

        def submit():
            page.locator("#submit-btn").click()
            page.locator("#stage-result .state-icon.ok").wait_for(timeout=90000)
            link = page.locator("#stage-result a[download]").first
            with page.expect_download() as pending:
                link.click()
            download = pending.value
            assert download.failure() is None
            return Path(download.path()).read_bytes()

        def pdf_pages(data):
            with pikepdf.open(io.BytesIO(data)) as doc:
                return len(doc.pages)

        def merge():
            upload("merge-pdf", 2)
            assert pdf_pages(submit()) == 6
            page.locator("#preview-btn").click()
            assert page.locator("iframe.preview-frame").is_visible()
            page.locator("#continue-btn").click()
            page.locator('#continue-menu [data-slug="compress-pdf"]').click()
            page.wait_for_url("**/compress-pdf")
            page.wait_for_function("() => Tool.readyFiles().length === 1")
            assert pdf_pages(submit()) == 6

        def extract():
            upload("extract-pdf-pages")
            page.locator('[name="pages"]').fill("1,3")
            page.locator('[name="pages"]').dispatch_event("input")
            assert pdf_pages(submit()) == 2

        def rotate():
            upload("rotate-pdf-pages")
            page.locator('#pages-ui .thumb').first.hover()
            page.locator('#pages-ui .thumb').first.locator('[data-rot="90"]').click()
            with pikepdf.open(io.BytesIO(submit())) as doc:
                assert int(doc.pages[0].obj.get("/Rotate", 0)) == 90
                assert int(doc.pages[1].obj.get("/Rotate", 0)) == 0

        def organize():
            upload("organize-pdf")
            page.locator('[data-blank-add]').click()
            assert pdf_pages(submit()) == 4

        def metadata():
            upload("edit-pdf-metadata")
            page.wait_for_function("() => document.querySelector('[name=\"metadata.Title\"]').value === 'Browser fixture'")
            page.locator('[name="metadata.Title"]').fill("Updated in browser")
            with pikepdf.open(io.BytesIO(submit())) as doc:
                assert str(doc.docinfo.Title) == "Updated in browser"

        def bookmarks():
            upload("pdf-bookmarks")
            page.wait_for_function("() => document.querySelector('[name=bookmarks]').value.includes('Chapter 1')")
            page.locator('[name="bookmarks"]').fill("Browser chapter | 1")
            with pikepdf.open(io.BytesIO(submit())) as doc:
                with doc.open_outline() as outline:
                    assert outline.root[0].title == "Browser chapter"

        def mix():
            upload("alternate-mix-pdf", 2)
            page.locator("[data-mix-step]").first.fill("2")
            page.locator("[data-mix-step]").first.dispatch_event("change")
            page.locator("[data-mix-reverse]").nth(1).check()
            assert pdf_pages(submit()) == 6

        def crop_groups():
            upload("crop-pdf")
            page.get_by_text("Draw an area", exact=True).click()
            page.get_by_text("Odd and even pages separately", exact=True).click()
            def draw(x, y, w, h):
                canvas = page.locator(".area-wrap canvas")
                page.wait_for_function("() => document.querySelector('.area-wrap canvas')?.width > 300")
                rect = canvas.bounding_box()
                page.mouse.move(rect["x"]+x, rect["y"]+y)
                page.mouse.down()
                page.mouse.move(rect["x"]+x+w, rect["y"]+y+h, steps=5)
                page.mouse.up()
            draw(10, 20, 180, 240)
            page.locator("[data-area-page]").select_option("2")
            draw(20, 30, 250, 280)
            with pikepdf.open(io.BytesIO(submit())) as doc:
                sizes = [(float(p.mediabox[2])-float(p.mediabox[0]), float(p.mediabox[3])-float(p.mediabox[1])) for p in doc.pages]
                assert abs(sizes[0][0]-sizes[2][0]) < .1 and sizes[1][0] > sizes[0][0] + 20

        def html():
            load("html-to-pdf")
            page.locator('[data-action="more"]').click()
            page.locator('[name="htmlCode"]').fill("<h1>Browser HTML conversion</h1>")
            assert pdf_pages(submit()) == 1

        def offline_preview():
            context.route("https://**/*", lambda route: route.abort())
            try:
                upload("extract-pdf-pages")
                page.wait_for_function("() => Array.from(document.querySelectorAll('#pages-ui canvas')).some(c => c.width > 0 && c.height > 0)")
                page.locator('[name="pages"]').fill("1")
                page.locator('[name="pages"]').dispatch_event("input")
                assert pdf_pages(submit()) == 1
            finally:
                context.unroute("https://**/*")

        def mobile():
            page.set_viewport_size({"width": 390, "height": 844})
            for slug in ("", "merge-pdf", "pdf-editor", "workflows", "developers", "html-pdf-api"):
                load(slug)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), f"Horizontal overflow on {slug}"
            page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1365, "height": 900})

        check("home search + persistent theme", home)
        for tool in api.get("/api/tools").json():
            check("page " + tool["slug"], lambda slug=tool["slug"]: shell(slug))
        for slug in ("workflows", "about", "help", "privacy", "terms", "developers", "html-pdf-api"):
            check("page " + slug, lambda slug=slug: shell(slug))
        for name, fn in [("merge, preview, continue, compress", merge), ("extract page selection", extract),
                         ("rotate thumbnail", rotate), ("organize blank page", organize),
                         ("metadata prefill + edit", metadata), ("bookmarks prefill + edit", bookmarks),
                         ("mix per-file options", mix), ("crop odd/even areas", crop_groups),
                         ("HTML conversion", html), ("preview with external network blocked", offline_preview), ("mobile layout", mobile)]:
            check(name, fn)
        browser.close()
    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = sum(not r["ok"] for r in results)
    print(f"{len(results)-failed}/{len(results)} checks passed")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
