# PDFNova (pdfsejeda)

A full-featured online PDF toolkit — 45+ tools: merge, split, compress, convert, edit, sign, OCR and more — built with Python (FastAPI). Its behaviour is modelled on the reverse-engineering notes in [research/SEJDA.md](research/SEJDA.md); branding, copy and design are original.

- **How it works (start here):** [sejedarules.md](sejedarules.md)
- **Build plan and progress:** [plan.md](plan.md)

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Optional engines (the app works without them; the tools that need them show a clear message):

| Tool | Needs |
|---|---|
| Word → PDF (exact layout) | LibreOffice (`soffice` on PATH) |
| OCR | Tesseract (`tesseract` on PATH) |
| HTML → PDF | `pip install playwright && playwright install chromium` |

## Run with Docker (everything included)

```bash
docker compose up --build
# open http://localhost:8000
```

Set `SECRET_KEY` in `docker-compose.yml` first. All settings are listed in [sejedarules.md §7](sejedarules.md).

## Test

```bash
pytest -q
```
