# Prarit Sidana PDF (pdfsejeda)

**Live app: [Prarit Sidana PDF](https://pdf.praritsidana.com/)**

[Edit a PDF](https://pdf.praritsidana.com/pdf-editor) | [Compress a PDF](https://pdf.praritsidana.com/compress-pdf) | [PDF guides](https://pdf.praritsidana.com/guides)

43 online PDF tools built with Python, FastAPI, Jinja2 and vanilla JavaScript: merge, split, compress, convert, edit, sign, OCR, forms and reusable workflows.

Behavior is informed by the local Sejda research; Prarit Sidana PDF uses its own branding and interface. This is not a claim of complete Sejda product parity. See [the verification report](research/audit-2026-10-22/REPORT.md) for tested behavior and remaining gaps.

- [How the app works and contributor rules](sejedarules.md)
- [Build plan](plan.md)

## Run locally on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt playwright
.\.venv\Scripts\python.exe -m playwright install chromium
# If you do not already have .env, copy .env.example to .env and choose a random SECRET_KEY.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. On macOS/Linux, use `.venv/bin/python` instead. Settings in the existing `.env` file are loaded automatically; environment variables override them.

For the exact tested Python dependency versions, install `requirements-lock.txt` instead. That snapshot includes Playwright and tests; Chromium still needs the browser-install command.

LibreOffice is required for DOC/ODT/RTF and faithful DOCX conversion. DOCX/TXT have a basic fallback with a warning. OCR requires Tesseract plus the selected language packs. HTML conversion requires Playwright Chromium. PDF previews use the included PDF.js files and do not need a CDN.

## Run with Docker

```sh
docker compose up --build
```

Create `.env` from `.env.example` and set `SECRET_KEY` first. The Docker image includes LibreOffice, Tesseract, language packs, fonts and Chromium. The Dockerfile was reviewed, but a Docker image build has not been verified on this workstation because Docker is unavailable.

Use one Uvicorn process: task records and quotas are held in memory. Multiple processes or hosts require a shared job store, queue and storage. Keep file/task IDs private: they grant access, and anyone with a task ID can retrieve its results. Results expire after completion; uploads use a sliding keep-alive lifetime.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# With a server already running:
.\.venv\Scripts\python.exe scripts/smoke_test.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/browser_regression.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/concurrency_regression.py http://127.0.0.1:8000
# Starts its own isolated temporary server:
.\.venv\Scripts\python.exe scripts/editor_regression.py
```

The HTTP smoke test covers all tool handlers and actual downloads, including external engines. Browser tests exercise navigation, upload, preview, actual downloads, continuation, mobile layouts, forms, recovery and workflows. They use generated local fixtures; Sejda is not used for PDF processing during these tests.

## API

Open `/developers` or `/html-pdf-api` for usage guides, `/api/docs` for the interactive API reference, and `/api/tools` for tool options. `/result?id=TASK_ID` reopens a live task in its tool page.

See [third-party notices](THIRD_PARTY_NOTICES.md) for vendored PDF.js provenance.
