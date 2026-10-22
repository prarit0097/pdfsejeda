"""Real Chromium regressions for editor recovery and workflow storage.

Runs its own temporary FastAPI server and leaves the developer's data untouched.
Run: python scripts/editor_regression.py
Set EDITOR_MOBILE_ONLY=1 to run just the touch editor checks.
Set EDITOR_BASE_URL=https://your-host to exercise an existing deployment instead.
"""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright
import pypdf
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS = ROOT / "data-qa-browser"


def sample():
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, invariant=1)
    for text in ("Editor regression one", "Editor regression two"):
        # Separate drawing operations exercise adjacent text-fragment search.
        offset = 72
        for fragment in text.split(" "):
            pdf.drawString(offset, 700, fragment + " ")
            offset += pdf.stringWidth(fragment + " ")
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def run():
    SCREENSHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdfnova-editor-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "NO_DOTENV": "1", "DATA_DIR": folder, "TASKS_PER_HOUR": "0"}
        external_base = os.environ.get("EDITOR_BASE_URL", "").rstrip("/")
        server = None if external_base else subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = external_base or f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(base, timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: (errors.append(str(error)), print("BROWSER ERROR:", error, flush=True)))
                upload = {"name": "same.pdf", "mimeType": "application/pdf", "buffer": sample()}
                if not os.environ.get("EDITOR_MOBILE_ONLY"):
                    page.goto(base + "/pdf-editor")
                    upload = {"name": "same.pdf", "mimeType": "application/pdf", "buffer": sample()}
                    page.locator("#file-input").set_input_files(upload)
                    page.wait_for_selector(".ed-pagewrap", timeout=30000)
                    assert page.locator(".ed-pagewrap").count() == 2
                    page.locator('[data-pa="rotr"]').first.click()
                    # Save immediately: submission must flush the pending autosave timer.
                    fake = "ABCDEF12-202610221234"
                    page.route("**/api/tasks", lambda route: route.fulfill(json=fake))
                    page.route(f"**/api/tasks/{fake}/change?*", lambda route: route.fulfill(json={"status": "Failed", "failureReason": "Injected regression failure"}))
                    page.locator('[data-action="save"]').click()
                    page.get_by_text("Injected regression failure").wait_for()
                    draft = page.evaluate("Object.keys(localStorage).find(k => k.startsWith('editorDraft:v2:'))")
                    assert draft and page.evaluate("k => JSON.parse(localStorage.getItem(k)).pages[0].rot", draft) == 90
                    print("PASS failed save retains structural draft, including immediate submit")
                    page.unroute("**/api/tasks")
                    page.unroute(f"**/api/tasks/{fake}/change?*")
                    page.goto(base + "/pdf-editor")
                    page.locator("#file-input").set_input_files(upload)
                    page.get_by_role("heading", name="Recover unsaved changes?").wait_for(timeout=30000)
                    page.get_by_role("button", name="Recover", exact=True).click()
                    page.wait_for_selector(".ed-pagewrap")
                    page.locator('[data-action="save"]').click()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    assert page.evaluate("k => localStorage.getItem(k)", draft) is None
                    page.reload()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    assert page.evaluate("k => localStorage.getItem(k)", draft) is None
                    print("PASS page-only draft recovers and clears only after completed save")
                    page.goto(base + "/pdf-editor")
                    page.evaluate("""() => {
                      localStorage.setItem('editorDraft:v2:expired-regression', JSON.stringify({at: Date.now() - 49 * 3600e3, pages: [], objects: []}));
                      localStorage.setItem('editorDraft:v2:corrupt-regression', '{broken');
                      localStorage.setItem('editorDraft:v2:recent-regression', JSON.stringify({at: Date.now(), pages: [], objects: []}));
                    }""")
                    page.locator("#file-input").set_input_files(upload)
                    page.wait_for_selector(".ed-pagewrap", timeout=30000)
                    assert page.evaluate("localStorage.getItem('editorDraft:v2:expired-regression')") is None
                    assert page.evaluate("localStorage.getItem('editorDraft:v2:corrupt-regression')") is None
                    assert page.evaluate("localStorage.getItem('editorDraft:v2:recent-regression')") is not None
                    page.locator('[data-action="find"]').click()
                    page.locator("#ed-find-text").fill("editor regression")
                    page.get_by_text("2 matches", exact=True).wait_for()
                    page.screenshot(path=str(SCREENSHOTS / "editor-find-desktop.png"), full_page=True)
                    page.locator("#ed-find-case").check()
                    page.get_by_text("No matches in horizontal text.", exact=True).wait_for()
                    page.locator("#ed-find-case").uncheck()
                    page.get_by_text("2 matches", exact=True).wait_for()
                    page.locator("#ed-replace-text").fill("Checked document")
                    page.locator("#ed-find-replace").click()
                    page.get_by_text("1 match", exact=True).wait_for()
                    page.locator('[data-action="undo"]').click()
                    page.get_by_text("2 matches", exact=True).wait_for()
                    page.locator("#ed-find-all").click()
                    page.get_by_text("No matches in horizontal text.", exact=True).wait_for()
                    page.reload()
                    page.locator("#file-input").set_input_files(upload)
                    page.get_by_role("heading", name="Recover unsaved changes?").wait_for(timeout=30000)
                    page.get_by_role("button", name="Recover", exact=True).click()
                    page.wait_for_selector(".obj.edittext")
                    assert page.locator(".obj.edittext").count() == 2
                    page.locator('[data-action="save"]').click()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    link = page.locator("#stage-result a[download]").first.get_attribute("href")
                    replacement_pdf = pypdf.PdfReader(io.BytesIO(context.request.get(link).body()))
                    assert "Checked document one" in replacement_pdf.pages[0].extract_text()
                    assert "Checked document two" in replacement_pdf.pages[1].extract_text()
                    print("PASS find/replace case matching, selected/all replacement, undo, immediate reload recovery, saved PDF text, expired-draft pruning")
                    page.goto(base + "/pdf-forms")
                    page.locator("#file-input").set_input_files(upload)
                    page.wait_for_selector(".ed-pagewrap", timeout=30000)
                    surface = page.locator(".ed-page").first
                    surface.click(position={"x": 120, "y": 80})
                    page.locator('[data-p="name"]').fill("pin")
                    page.locator('[data-p="value"]').fill("1234")
                    page.locator('[data-p="maxLength"]').fill("4")
                    page.locator('[data-c="comb"]').check()
                    page.locator('[data-tool="field-dropdown"]').click()
                    surface.click(position={"x": 120, "y": 140})
                    page.locator('[data-p="name"]').fill("country")
                    page.locator('[data-p="options"]').fill("France\nIndia\nBrazil")
                    page.locator('[data-p="value"]').fill("India")
                    page.locator('[data-tool="field-listbox"]').click()
                    surface.click(position={"x": 120, "y": 210})
                    page.locator('[data-p="name"]').fill("topics")
                    page.locator('[data-p="options"]').fill("one\ntwo\nthree")
                    page.locator('[data-c="multiSelect"]').check()
                    page.locator('[data-p="value"]').fill("one\nthree")
                    page.locator('[data-tool="field-radio"]').click()
                    surface.click(position={"x": 120, "y": 320})
                    page.locator('[data-p="name"]').fill("priority")
                    page.locator('[data-p="exportValue"]').fill("Low")
                    page.locator('[data-tool="field-radio"]').click()
                    surface.click(position={"x": 200, "y": 320})
                    page.locator('[data-p="exportValue"]').fill("High")
                    page.locator('[data-c="value"]').check()
                    page.locator('[data-action="save"]').click()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    link = page.locator("#stage-result a[download]").first.get_attribute("href")
                    output = context.request.get(link)
                    assert output.ok
                    fields = pypdf.PdfReader(io.BytesIO(output.body())).get_fields()
                    assert fields["pin"]["/V"] == "1234" and int(fields["pin"]["/Ff"]) & (1 << 24)
                    assert fields["country"]["/V"] == "India"
                    assert list(fields["topics"]["/V"]) == ["one", "three"]
                    assert fields["priority"]["/V"] == "/High"
                    print("PASS browser-created comb text, dropdown, multiselect listbox, grouped radios save real PDF values")
                    page.goto(base + "/sign-pdf")
                    page.locator("#file-input").set_input_files({"name": "created-forms.pdf", "mimeType": "application/pdf", "buffer": output.body()})
                    page.locator('select[data-field="topics"]').wait_for(timeout=30000)
                    page.locator('select[data-field="topics"]').select_option(["two", "three"])
                    page.locator('select[data-field="country"]').select_option("France")
                    page.locator('input[data-field="pin"]').fill("9876")
                    page.locator('input[data-field="priority"][value="Low"]').check()
                    page.locator('[data-action="save"]').click()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    link = page.locator("#stage-result a[download]").first.get_attribute("href")
                    fields = pypdf.PdfReader(io.BytesIO(context.request.get(link).body())).get_fields()
                    assert fields["pin"]["/V"] == "9876" and fields["country"]["/V"] == "France"
                    assert list(fields["topics"]["/V"]) == ["two", "three"] and fields["priority"]["/V"] == "/Low"
                    print("PASS browser fills and saves existing multiselect, dropdown, comb text, radio values")
                    page.goto(base + "/workflows")
                    incoming = {"workflows": [{"id": "sensitive", "name": "Credential regression", "steps": [{"type": "encrypt", "title": "Encrypt", "userPassword": "DONT-PERSIST-OPEN", "ownerPassword": "DONT-PERSIST-OWNER", "nested": {"apiToken": "DONT-PERSIST-TOKEN"}, "files": ["OLD-FILE-ID"]}, {"type": "pageNumbers", "title": "Page numbers"}]}]}
                    page.locator("#wf-import-input").set_input_files({"name": "workflow.json", "mimeType": "application/json", "buffer": json.dumps(incoming).encode()})
                    page.get_by_text("Credential regression", exact=True).wait_for()
                    stored = page.evaluate("localStorage.getItem('workflows')")
                    assert "DONT-PERSIST" not in stored and "OLD-FILE-ID" not in stored
                    page.get_by_role("button", name="Use workflow Credential regression").click()
                    page.locator("#file-input").set_input_files(upload)
                    page.wait_for_function("() => Tool.readyFiles().length === 1")
                    page.locator("#submit-btn").click()
                    page.get_by_role("heading", name="Encryption password").wait_for()
                    page.locator('input[name="userPassword"]').fill("runtime-only-secret")
                    page.get_by_role("button", name="Continue", exact=True).click()
                    page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    assert "runtime-only-secret" not in page.evaluate("JSON.stringify({...localStorage, ...sessionStorage})")
                    print("PASS imported credentials scrubbed; encryption prompts at runtime without persistence")
                    assert not errors, errors
                    blocked = browser.new_context(ignore_https_errors=True)
                    blocked.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() {throw new DOMException('Storage disabled', 'SecurityError')}})")
                    blocked_page = blocked.new_page()
                    blocked_page.on("pageerror", lambda error: errors.append(str(error)))
                    blocked_page.goto(base + "/compress-pdf")
                    blocked_page.locator("#file-input").set_input_files(upload)
                    blocked_page.wait_for_function("() => Tool.readyFiles().length === 1")
                    blocked_page.locator("#submit-btn").click()
                    blocked_page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                    assert not errors, errors
                    print("PASS normal tool completes with sessionStorage disabled; no JavaScript exceptions")
                mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, ignore_https_errors=True)
                mobile_page = mobile.new_page()
                mobile_page.on("pageerror", lambda error: errors.append(str(error)))
                mobile_page.goto(base + "/pdf-editor")
                mobile_page.locator("#file-input").set_input_files(upload)
                mobile_page.wait_for_selector(".ed-pagewrap", timeout=30000)
                assert mobile_page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile document overflows horizontally"
                mobile_page.locator('[data-tool="edittext"]').tap()
                mobile_page.locator(".edit-span").first.wait_for()
                mobile_page.locator(".edit-span").first.tap()
                mobile_page.locator(".obj.edittext [contenteditable]").fill("Mobile updated original")
                mobile_page.locator('[data-tool="text"]').tap()
                mobile_surface = mobile_page.locator(".ed-page").first
                mobile_surface.tap(position={"x": 100, "y": 210})
                mobile_page.locator(".obj.text:not(.edittext) [contenteditable]").fill("Added on mobile")
                mobile_page.locator('[data-tool="field-check"]').tap()
                mobile_surface.tap(position={"x": 240, "y": 280})
                mobile_page.locator('[data-c="value"]').check()
                mobile_page.locator('[data-tool="select"]').tap()
                assert mobile_page.locator('[data-tool="select"]').get_attribute("aria-pressed") == "true"
                assert mobile_page.locator(".ed-bar button").evaluate_all("buttons => buttons.every(b => b.title && b.getBoundingClientRect().height >= 44)")
                mobile_page.screenshot(path=str(SCREENSHOTS / "editor-mobile-active.png"))
                before = mobile_page.evaluate("scrollY + document.querySelector('.ed-pages').scrollTop")
                cdp = mobile.new_cdp_session(mobile_page)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 350, "y": 650}]})
                for y in (600, 550, 500, 450, 400, 350, 300):
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 350, "y": y}]})
                    mobile_page.wait_for_timeout(60)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                mobile_page.wait_for_function("before => scrollY + document.querySelector('.ed-pages').scrollTop > before", arg=before)
                mobile_page.wait_for_function("""() => {
                  const position = scrollY + document.querySelector('.ed-pages').scrollTop;
                  if (window._scrollPosition !== position) { window._scrollPosition = position; window._scrollStableAt = performance.now(); return false; }
                  return performance.now() - window._scrollStableAt > 500;
                }""")
                mobile_page.locator('[data-action="save"]').tap()
                try:
                    mobile_page.get_by_role("heading", name="Your file is ready").wait_for(timeout=30000)
                except Exception:
                    print("MOBILE FAILURE:", ascii(mobile_page.locator("body").inner_text()[-1600:]), errors)
                    mobile_page.screenshot(path=str(SCREENSHOTS / "editor-mobile-failure.png"), full_page=True)
                    raise
                link = mobile_page.locator("#stage-result a[download]").first.get_attribute("href")
                saved = pypdf.PdfReader(io.BytesIO(mobile.request.get(link).body()))
                assert "Mobile updated original" in saved.pages[0].extract_text()
                assert "Added on mobile" in saved.pages[0].extract_text()
                assert saved.get_fields()["check1"]["/V"] == "/Yes"
                assert not errors, errors
                print("PASS mobile 390x844 touch: edit existing text, add text+checkbox, access toolbar, scroll, save actual PDF")
                browser.close()
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    run()
