"""Check signature ink retention and paper removal through the real browser UI.

Uses generated photos only. An optional --image path is inspected locally in the
browser for visual review; its bytes are not included in the server save test.
Usage: python scripts/signature_cleanup_regression.py http://127.0.0.1:8000
"""
import argparse
import base64
import io
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from playwright.sync_api import sync_playwright
import pypdf
import pypdfium2
from reportlab.pdfgen import canvas


OUT = Path("data-qa-transparency")


def photo(paper=(135, 137, 126), ink=(12, 18, 70), margins=False, shadow=False, transparent=False):
    w, h = (900, 1200) if margins else (420, 280)
    x, y = (300, 650) if margins else (50, 60)
    pixels = np.full((h, w, 3), 255, dtype=np.uint8)
    for row in range(150):
        shade = int(28 * row / 150) if shadow else 0
        pixels[y + row, x:x + 300] = [max(0, c - shade) for c in paper]
    image = Image.fromarray(pixels)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    points = [(x + 24, y + 105), (x + 65, y + 25), (x + 80, y + 105), (x + 145, y + 48), (x + 195, y + 95), (x + 270, y + 75)]
    draw.line(points, fill=255, width=5)
    draw.ellipse((x + 165, y + 20, x + 169, y + 24), fill=255)
    image.paste(ink, mask=mask)
    paper_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(paper_mask).rectangle((x + 8, y + 8, x + 291, y + 141), fill=255)
    # Keep background checks away from the real pen edge/antialiasing footprint.
    truth = np.asarray(mask) > 240
    away = np.asarray(mask.filter(ImageFilter.MaxFilter(17))) == 0
    background = (np.asarray(paper_mask) > 240) & away
    if transparent:
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        image.paste((*ink, 255), mask=mask)
    stream = io.BytesIO()
    image.save(stream, "PNG" if transparent else "JPEG", quality=93)
    return stream.getvalue(), truth, background


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--image", type=Path)
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    source = io.BytesIO()
    pdf = canvas.Canvas(source)
    pdf.setFillColorRGB(1, .85, .25)
    pdf.rect(0, 0, 595.28, 841.89, stroke=0, fill=1)
    pdf.showPage()
    pdf.save()
    errors = []
    cases = [
        ("navy-grey-cutout", dict(margins=True)),
        ("navy-dark-paper", dict(paper=(85, 88, 80))),
        ("black-grey-paper", dict(ink=(15, 15, 15))),
        ("black-shadowed-paper", dict(paper=(145, 145, 145), ink=(15, 15, 15), shadow=True)),
        ("blue-beige-paper", dict(paper=(180, 168, 140), ink=(15, 30, 120), shadow=True)),
        ("red-grey-paper", dict(ink=(135, 12, 20))),
        ("faint-grey-on-white", dict(paper=(255, 255, 255), ink=(160, 160, 160))),
        ("already-transparent", dict(transparent=True)),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1365, "height": 940})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base.rstrip("/") + "/pdf-editor")
        page.locator("#file-input").set_input_files({"name": "yellow-background.pdf", "mimeType": "application/pdf", "buffer": source.getvalue()})
        page.wait_for_selector(".ed-page canvas.pdf")
        page.locator('[data-tool="sign"]').click()
        page.get_by_role("button", name="+ New Signature", exact=True).click()
        page.get_by_role("tab", name="Upload Image", exact=True).click()

        def versions(blob, name):
            started = time.monotonic()
            page.locator("#signature-image-file").set_input_files({"name": name, "mimeType": "image/png" if name.endswith(".png") else "image/jpeg", "buffer": blob})
            page.locator('[data-versions="upload"] img').first.wait_for()
            urls = page.locator('[data-versions="upload"] img').evaluate_all("imgs => imgs.map(i => i.src)")
            images = [Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA") for url in urls]
            assert len(images) == 3 and len({im.size for im in images}) == 1, "Preview geometry differs"
            widths = page.locator('[data-versions="upload"] img').evaluate_all("imgs => imgs.map(i => i.getBoundingClientRect().width)")
            assert min(widths) > 0 and max(widths) - min(widths) < 2
            return images, time.monotonic() - started

        for name, options in cases:
            blob, ink, paper = photo(**options)
            images, seconds = versions(blob, name + (".png" if options.get("transparent") else ".jpg"))
            alpha = np.asarray(images[1])[:, :, 3]
            retained = float((alpha[ink] >= 140).mean())
            residual = float(alpha[paper].mean())
            assert retained > .96, (name, "Lost ink", retained)
            assert residual < 5, (name, "Paper remains", residual)
            if name == "navy-grey-cutout":
                assert np.asarray(images[2])[:, :, 3][paper].mean() > 245, "Conservative B should retain grey paper"
                assert np.asarray(images[2])[:, :, 3][0, 0] == 0
            print(f"PASS {name}: ink retained {retained:.1%}, paper alpha {residual:.2f}/255, {seconds:.2f}s", flush=True)

        # Save only a generated photo: the yellow PDF must show through the paper.
        blob, _, _ = photo()
        versions(blob, "generated-save.jpg")
        page.get_by_role("button", name="Transparent A", exact=True).click()
        page.locator("[data-remember]").uncheck()
        page.screenshot(path=str(OUT / "generated-comparison.png"))
        page.locator("[data-ok]").click()
        page.locator(".ed-page").click(position={"x": 240, "y": 300})
        page.locator('[data-action="save"]').click()
        page.get_by_role("heading", name="Your file is ready").wait_for(timeout=90000)
        link = page.locator("#stage-result a[download]").first.get_attribute("href")
        response = context.request.get(link)
        assert response.ok
        reader = pypdf.PdfReader(io.BytesIO(response.body()))
        signatures = list(reader.pages[0].images)
        assert signatures and any("/SMask" in im.indirect_reference.get_object() for im in signatures)
        doc = pypdfium2.PdfDocument(response.body())
        rendered = np.asarray(doc[0].render(scale=1).to_pil().convert("RGB"))
        # A grey rectangle would create neutral midtones, unlike yellow paper + navy ink.
        neutral = (np.ptp(rendered.astype(int), axis=2) < 18) & (rendered.mean(axis=2) > 70) & (rendered.mean(axis=2) < 210)
        assert neutral.sum() < 20, f"Grey paper visible in PDF: {neutral.sum()} pixels"
        assert ((rendered[:, :, 2] > rendered[:, :, 0] + 20) & (rendered[:, :, 0] < 80)).sum() > 30
        doc.close()
        print("PASS saved PDF: yellow page shows through, navy ink retained, no grey paper rectangle", flush=True)

        if args.image:
            page.goto(args.base.rstrip("/") + "/pdf-editor")
            page.locator("#file-input").set_input_files({"name": "review.pdf", "mimeType": "application/pdf", "buffer": source.getvalue()})
            page.wait_for_selector(".ed-page")
            page.locator('[data-tool="sign"]').click()
            page.get_by_role("button", name="+ New Signature", exact=True).click()
            page.get_by_role("tab", name="Upload Image", exact=True).click()
            images, seconds = versions(args.image.read_bytes(), "private-review.jpg")
            for index, im in enumerate(images):
                im.save(OUT / f"private-preview-{index}.png")
            page.screenshot(path=str(OUT / "private-comparison.png"))
            print(f"Local private-photo review prepared in {seconds:.2f}s; no save submitted", flush=True)
        assert not errors, errors
        browser.close()
    print("9/9 transparency checks passed")


if __name__ == "__main__":
    main()
