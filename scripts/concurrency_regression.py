"""Exercise simultaneous native PDF jobs against a running server (no external service).

Usage: python scripts/concurrency_regression.py http://127.0.0.1:8000
Requires capacity for 16 jobs and a disabled/sufficient hourly quota.
"""
import asyncio
import io
import sys
import time
import zipfile

import httpx
import pikepdf
from reportlab.pdfgen import canvas


async def run(base):
    data = io.BytesIO()
    pdf = canvas.Canvas(data)
    for i in range(3):
        pdf.drawString(72, 740, f"Concurrent page {i+1}")
        pdf.showPage()
    pdf.save()
    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        response = await client.post("/api/files/upload", files={"file": ("concurrent.pdf", data.getvalue(), "application/pdf")})
        response.raise_for_status()
        fid = response.json()["id"]
        cases = [{"type": "crop"}, {"type": "flatten", "flattenMode": "all", "resolution": 75},
                 {"type": "pdfToImage", "resolution": 75}, {"type": "deskew"},
                 {"type": "pdfToPpt"}, {"type": "extractText"},
                 {"type": "extractPages", "pages": "1-2"}, {"type": "rotatePages", "rotation": 90}] * 2

        async def task(options):
            response = await client.post("/api/tasks", json={**options, "files": [fid]})
            response.raise_for_status()
            tid = response.json()
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    response = await client.get(f"/api/tasks/{tid}/change")
                    response.raise_for_status()
                    result = response.json()
                    if result["status"] == "Failed":
                        raise AssertionError(result.get("failureReason"))
                    if result["status"] == "Completed":
                        break
                    await asyncio.sleep(.15)
                else:
                    raise AssertionError("Task exceeded regression deadline")
                url = base.split(":", 1)[0] + "://" + result["resultFullUrlPattern"].replace("%7B%7Bfilename%7D%7D", result["resultFilename"])
                response = await client.get(url)
                response.raise_for_status()
                blob, name = response.content, result["resultFilename"]
                if name.endswith(".pdf"):
                    with pikepdf.open(io.BytesIO(blob)) as pdf:
                        assert len(pdf.pages) == (2 if options["type"] == "extractPages" else 3)
                elif name.endswith(".txt"):
                    assert b"Concurrent page 3" in blob
                else:
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                        assert archive.namelist()
                        assert archive.testzip() is None
                print("PASS", options["type"], name, flush=True)
            finally:
                await client.delete(f"/api/tasks/{tid}")

        await asyncio.gather(*(task(case) for case in cases))
        print(f"{len(cases)}/{len(cases)} concurrent tasks passed")


if __name__ == "__main__":
    asyncio.run(run((sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")))
