# PDFNova (pdfsejeda)

A full-featured online PDF toolkit — merge, split, compress, convert, edit, sign and ~40 more tools — built with Python (FastAPI). Its behaviour is modelled on the reverse-engineering notes in [research/SEJDA.md](research/SEJDA.md); branding, copy and design are original.

- **How it works:** [sejedarules.md](sejedarules.md)
- **Build plan:** [plan.md](plan.md)

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

## Test

```bash
pytest -q
```
