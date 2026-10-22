"""Real Chromium signature creation, reuse, cleanup and downloaded-PDF checks.

Usage: python scripts/signature_regression.py http://127.0.0.1:8000
Generated fixtures only. Camera tests use a synthetic local MediaStream, never a
physical camera. Four tasks are submitted; allow sufficient test quota.
"""
import base64
import io
from pathlib import Path
import sys

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
import pypdf
import pypdfium2
from reportlab.pdfgen import canvas


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
OUT = Path("data-qa-signature")


def fixture():
    data = io.BytesIO()
    pdf = canvas.Canvas(data)
    pdf.drawString(72, 760, "Signature test fixture")
    pdf.showPage()
    pdf.save()
    return data.getvalue()


def signature_photo():
    image = Image.new("RGB", (360, 150), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 30, 290, 125), fill=(170, 170, 170))
    draw.line([(70, 100), (130, 48), (150, 100), (220, 60), (270, 90)], fill=(15, 25, 165), width=5)
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def main():
    OUT.mkdir(exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1365, "height": 940})
        context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_default_timeout(20000)

        def upload(target=page):
            target.goto(BASE + "/pdf-editor")
            target.locator("#file-input").set_input_files({"name": "signature.pdf", "mimeType": "application/pdf", "buffer": fixture()})
            target.wait_for_selector(".ed-page canvas.pdf")

        def create(target=page):
            target.locator('[data-tool="sign"]').click()
            target.get_by_role("button", name="+ New Signature", exact=True).click()
            target.get_by_role("dialog", name="Create signature").wait_for()

        def place(target=page):
            target.locator(".ed-page").first.click(position={"x": 250, "y": 350})
            target.locator(".signature-object").wait_for()
            assert target.locator('[data-tool="select"]').get_attribute("aria-pressed") == "true"
            for point in ({"x": 40, "y": 70}, {"x": 90, "y": 140}):
                target.locator(".ed-page").first.click(position=point)
            assert target.locator(".signature-object").count() == 1, "Placement stayed armed"
            target.locator(".signature-object").click()

        def save_pdf(target=page, session=context):
            target.locator('[data-action="save"]').click()
            target.get_by_role("heading", name="Your file is ready").wait_for(timeout=90000)
            url = target.locator("#stage-result a[download]").first.get_attribute("href")
            response = session.request.get(url)
            assert response.ok
            reader = pypdf.PdfReader(io.BytesIO(response.body()))
            assert len(reader.pages) == 1 and len(reader.pages[0].images) > 0
            return response.body()

        upload()
        create()
        page.locator("[data-ok]").click()
        assert page.get_by_role("alert").filter(has_text="Type your name first").is_visible()
        page.get_by_role("textbox", name="Your name").fill("Ada Lovelace")
        assert page.locator("[data-font]").count() == 12
        page.evaluate("document.fonts.ready")
        assert page.evaluate("Array.from(document.querySelectorAll('[data-font]')).every(b => document.fonts.check(`30px '${b.dataset.font}'`))")
        page.get_by_role("button", name="Great Vibes", exact=True).click()
        page.locator('[data-pane="type"] [data-color="#0000ff"]').click()
        page.screenshot(path=str(OUT / "type-desktop.png"))
        page.locator("[data-ok]").click()
        page.get_by_role("dialog").wait_for(state="hidden")
        assert page.evaluate("JSON.parse(localStorage.signatures).length") == 1
        place()
        # SVG icons must fit distinct buttons rather than inherit full-object SVG positioning.
        def check_actions(target):
            buttons = target.locator(".signature-object.sel [data-object-action]")
            assert buttons.count() == 3
            bounds = [buttons.nth(i).bounding_box() for i in range(3)]
            for i, box in enumerate(bounds):
                icon = buttons.nth(i).locator("svg").bounding_box()
                assert box and icon and 14 <= icon["width"] <= 24 and 14 <= icon["height"] <= 24
                assert box["x"] <= icon["x"] and icon["x"] + icon["width"] <= box["x"] + box["width"] + 1
                if i: assert box["x"] >= bounds[i-1]["x"] + bounds[i-1]["width"] - 1
            target.screenshot(path=str(OUT / ("actions-mobile.png" if target.viewport_size["width"] < 600 else "actions-desktop.png")))
        check_actions(page)
        original = page.locator(".signature-object img").get_attribute("src")
        image = Image.open(io.BytesIO(base64.b64decode(original.split(",", 1)[1])))
        page.get_by_role("button", name="Rotate signature", exact=True).click()
        page.wait_for_function("src => document.querySelector('.signature-object img').src !== src", arg=original)
        rotated = Image.open(io.BytesIO(base64.b64decode(page.locator(".signature-object img").get_attribute("src").split(",", 1)[1])))
        assert rotated.size == (image.height, image.width)
        page.get_by_role("button", name="Duplicate signature", exact=True).click()
        assert page.locator(".signature-object").count() == 2
        page.get_by_role("button", name="Delete signature", exact=True).click()
        assert page.locator(".signature-object").count() == 1
        obj = page.locator(".signature-object")
        obj.click()
        before = obj.bounding_box()
        page.mouse.move(before["x"] + before["width"] / 2, before["y"] + before["height"] / 2)
        page.mouse.down()
        page.mouse.move(before["x"] + before["width"] / 2 + 45, before["y"] + before["height"] / 2 + 25, steps=5)
        page.mouse.up()
        assert obj.bounding_box()["x"] > before["x"] + 30
        obj.locator("[data-handle]").evaluate("el => el.scrollIntoView({block:'center'})")
        handle = obj.locator("[data-handle]").bounding_box()
        page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
        page.mouse.down()
        page.mouse.move(handle["x"] + 35, handle["y"] + 35, steps=5)
        page.mouse.up()
        assert obj.bounding_box()["width"] > before["width"], (before, handle, obj.bounding_box())
        data = save_pdf()
        doc = pypdfium2.PdfDocument(data)
        rendered = doc[0].render(scale=1).to_pil().convert("RGB")
        assert sum(b > 130 and r < 80 and g < 80 for r, g, b in rendered.get_flattened_data()) > 30
        doc.close()
        print("PASS typed signature: 12 local fonts, colour, saved library, rotate/duplicate/delete, drag/resize and blue pixels in actual PDF", flush=True)

        upload()
        page.locator('[data-tool="sign"]').click()
        page.get_by_role("button", name="Use saved signature 1", exact=True).click()
        place()
        page.locator('[data-tool="sign"]').click()
        page.get_by_role("button", name="Use saved signature 1", exact=True).click()
        page.locator(".ed-page").click(position={"x": 450, "y": 500})
        assert page.locator(".signature-object").count() == 2
        assert page.locator('[data-tool="select"]').get_attribute("aria-pressed") == "true"
        page.get_by_role("button", name="Delete signature", exact=True).click()
        assert page.locator(".signature-object").count() == 1
        page.locator('[data-tool="sign"]').click()
        page.get_by_role("button", name="Remove saved signature 1", exact=True).click()
        assert page.locator(".signature-object").count() == 1
        assert page.evaluate("JSON.parse(localStorage.signatures).length") == 0
        page.keyboard.press("Escape")
        page.reload()
        upload()
        create()
        page.get_by_role("tab", name="Upload Image", exact=True).click()
        with page.expect_file_chooser() as pending:
            page.get_by_role("button", name="Choose signature image", exact=True).click()
        pending.value.set_files({"name": "signature-photo.png", "mimeType": "image/png", "buffer": signature_photo()})
        page.locator('[data-versions="upload"] button').first.wait_for()
        sources = page.locator('[data-versions="upload"] img').evaluate_all("imgs => imgs.map(i => i.src)")
        images = [Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGBA") for src in sources]
        assert images[0].getextrema()[3] == (255, 255)
        assert images[1].getextrema()[3][0] == 0 and images[2].getextrema()[3][0] == 0
        assert sources[1] != sources[2]
        page.get_by_role("button", name="Transparent B", exact=True).click()
        page.locator("[data-remember]").uncheck()
        page.screenshot(path=str(OUT / "image-versions-desktop.png"))
        page.locator("[data-ok]").click()
        place()
        assert page.evaluate("JSON.parse(localStorage.signatures).length") == 0
        data = save_pdf()
        reader = pypdf.PdfReader(io.BytesIO(data))
        assert any("/SMask" in value.indirect_reference.get_object() for value in reader.pages[0].images)
        print("PASS saved reuse/removal across reload, Original/Transparent A/B pixels, unchecked persistence and PDF transparency mask", flush=True)

        upload()
        create()
        page.get_by_role("tab", name="Camera", exact=True).click()
        page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; }")
        page.get_by_role("button", name="Start camera", exact=True).click()
        page.get_by_role("status").filter(has_text="Camera access was not available").wait_for()
        page.evaluate("""() => { navigator.mediaDevices.getUserMedia = async () => {
          const c = document.createElement('canvas'); c.width = 360; c.height = 150;
          const x = c.getContext('2d'); x.fillStyle = 'white'; x.fillRect(0,0,360,150);
          x.strokeStyle = 'blue'; x.lineWidth = 4; x.beginPath(); x.moveTo(30,100); x.lineTo(120,35); x.lineTo(200,110); x.stroke();
          window.testCameraStream = c.captureStream(10); return window.testCameraStream;
        }; }""")
        page.get_by_role("button", name="Start camera", exact=True).click()
        page.get_by_role("button", name="Take photo", exact=True).wait_for()
        page.wait_for_function("() => !document.querySelector('[data-camera-capture]').disabled")
        page.get_by_role("tab", name="Type", exact=True).click()
        assert page.evaluate("testCameraStream.getTracks().every(t => t.readyState === 'ended')")
        page.get_by_role("tab", name="Camera", exact=True).click()
        page.get_by_role("button", name="Start camera", exact=True).click()
        page.wait_for_function("() => !document.querySelector('[data-camera-capture]').disabled")
        page.get_by_role("button", name="Take photo", exact=True).click()
        page.locator('[data-versions="camera"] button').first.wait_for()
        assert page.evaluate("testCameraStream.getTracks().every(t => t.readyState === 'ended')")
        page.locator("[data-remember]").uncheck()
        page.locator("[data-ok]").click()
        place()
        save_pdf()
        print("PASS camera denial/fallback, synthetic capture, image variants, track cleanup on tab switch/capture and real PDF output", flush=True)

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        touch = mobile.new_page()
        touch.on("pageerror", lambda e: errors.append(str(e)))
        upload(touch)
        create(touch)
        touch.get_by_role("tab", name="Draw", exact=True).tap()
        touch.locator("[data-ok]").tap()
        assert touch.get_by_role("alert").filter(has_text="Draw your signature first").is_visible()
        touch.locator(".sig-pad").tap(position={"x": 80, "y": 70})
        touch.get_by_role("button", name="Clear", exact=True).tap()
        touch.locator("[data-ok]").tap()
        assert touch.get_by_role("alert").is_visible()
        touch.locator(".sig-pad").tap(position={"x": 100, "y": 80})
        assert touch.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        touch.screenshot(path=str(OUT / "draw-mobile.png"))
        touch.locator("[data-remember]").uncheck()
        touch.locator("[data-ok]").tap()
        place(touch)
        check_actions(touch)
        touch.get_by_role("button", name="Duplicate signature", exact=True).tap()
        assert touch.locator(".signature-object").count() == 2
        touch.get_by_role("button", name="Delete signature", exact=True).tap()
        assert touch.locator(".signature-object").count() == 1
        save_pdf(touch, mobile)
        upload(touch)
        create(touch)
        touch.keyboard.press("Escape")
        assert touch.get_by_role("dialog").count() == 0
        blocked = browser.new_context()
        blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new DOMException('Storage disabled', 'SecurityError')}})")
        private_page = blocked.new_page()
        private_page.on("pageerror", lambda e: errors.append(str(e)))
        upload(private_page)
        create(private_page)
        private_page.get_by_role("textbox", name="Your name").fill("Temporary signature")
        private_page.locator("[data-ok]").click()
        place(private_page)
        assert private_page.locator(".signature-object").count() == 1
        print("PASS mobile touch drawing/dot, clear/empty validation, no horizontal overflow, save PDF and Escape close", flush=True)
        assert not errors, errors
        browser.close()
    print("4/4 signature scenario groups passed")


if __name__ == "__main__":
    main()
