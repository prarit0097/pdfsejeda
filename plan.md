# plan.md — build plan, start to finish

This is the master plan for this repo. Work follows it phase by phase. When a phase or task is done, tick it here **and** log it in [sejedarules.md](sejedarules.md).

Source of truth for *behaviour*: [research/SEJDA.md](research/SEJDA.md) (reverse-engineering of sejda.com).
Goal: a functional replica of sejda.com — same tools, same options, same upload → task → poll → download flow, same editor model — with **original branding, original page copy and original design**. Sejda's name, logo, text and shipped JS are not copied (trademark/copyright); see "Ground rules" in sejedarules.md.

Remote: https://github.com/prarit0097/pdfsejeda (push after every completed unit of work).

---

## 1. Technology decisions

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12+** | requested; best PDF library ecosystem with permissive licences |
| Web framework | **FastAPI** + Uvicorn | async, typed, fast; serves both API and HTML |
| HTML | **Jinja2** server-rendered pages, one page per tool (like Sejda) | SEO-friendly, no SPA build step |
| Front-end JS | Vanilla ES modules, no framework | small, fast; Sejda's UX does not need React |
| Styling | Hand-written CSS with design tokens, light + dark themes | original design, no CSS framework lock-in |
| PDF preview | **PDF.js** (Apache-2.0), loaded from CDN | same role as on Sejda |
| PDF core | **pikepdf** (qpdf, MPL-2.0) + **pypdf** (BSD) | structural edits, encryption, outlines, forms |
| Rendering | **pypdfium2** (Apache/BSD) | page → image, thumbnails, auto-crop, deskew, flatten |
| Drawing overlays | **reportlab** (BSD) | text, page numbers, Bates, watermarks, editor ops |
| Text / tables | **pdfplumber** (MIT) | extract text, split/rename by text, PDF → Excel |
| Office output | python-docx, python-pptx, openpyxl | PDF → Word / PPT / Excel |
| Images | Pillow, numpy | image re-encoding (compress), deskew angle detection |
| Optional external | LibreOffice (Word→PDF), Tesseract/OCRmyPDF (OCR), Playwright Chromium (HTML→PDF) | detected at runtime; tool shows a clear error if missing; all bundled in the Docker image |
| Job queue | In-process `ThreadPoolExecutor` behind a `JobQueue` interface | zero infra for dev; swappable for Redis/RQ later |
| Storage | Local disk behind a `FileStore` interface, 2-hour TTL sweeper | mirrors Sejda's "deleted after 2 hours" |
| Tests | pytest + FastAPI TestClient | every tool gets at least one test |
| Deploy | Dockerfile (Debian + LibreOffice + Tesseract + Chromium) | one image runs everything |

**Licence rule:** no AGPL dependencies (no PyMuPDF, no Ghostscript, no Sejda SDK) so the server can stay closed or open as the owner chooses.

---

## 2. Architecture (mirrors research/SEJDA.md Part 1 §1)

```
Browser (tool page, vanilla JS)
  1. POST /api/files/upload            multipart  → {"id": fileId}
     POST /api/files/upload-chunked    5 MB chunks with Content-Range (big files)
     POST /api/files {"url": …}        import by link → {"id": fileId}
  2. POST /api/tasks {type, files:[ids], …options}
        200 → "TASKID-yyyyMMddHHmm"  + x-ratelimit-remaining / x-ratelimit-wait
        402 {reason:"tasks-per-hour"} | 400 text | 429
  3. GET  /api/tasks/<id>/change       poll every 3 s → {status, remark, resultFilename,
                                         resultFileSize, resultFullUrlPattern, warnings, resultItems}
  4. GET  /api/tasks/<id>/download/<name>?s=<HMAC>&d=true     (bearer link, expires with files)
     POST /api/tasks/<id>/cancel   DELETE /api/tasks/<id>
Server
  FileStore (disk, TTL 2 h) ← JobQueue (threads) → tool handler registry  type → function
```

Editor: PDF.js renders in the browser; the browser sends **operation arrays** (`appendTextOperations`, `shapeOperations`, …) in one `edit` task; the server applies them. Coordinates = PDF points, bottom-left origin (the research's one top-left exception, `editTextOperations.area`, is normalised to bottom-left in our API).

---

## 3. Phases

### Phase 0 — Planning & docs
- [x] plan.md (this file)
- [x] sejedarules.md (living "how the app works" doc + rules)
- [x] Repo init, .gitignore, README, push

### Phase 1 — Platform core
- [x] `app/config.py` settings (env-driven: APP_NAME, limits, secrets, storage dir)
- [x] `app/storage.py` FileStore: ids `<uuid>-<16 chars>_1`, metadata, TTL sweeper, touch
- [x] `app/pages.py` page-selection parser (`"1-3,7"`, `odd`, `even`, `all`, `5-`, numbers)
- [x] `app/jobs.py` JobQueue + Task records, ids `<8 chars>-<yyyyMMddHHmm>`, statuses Queued/Processing/Completed/Failed, cancel
- [x] `app/security.py` HMAC download signature `web-…`, SSRF-safe URL import
- [x] `app/ratelimit.py` per-IP tasks-per-hour (402 like Sejda), configurable
- [x] API routes: upload, upload-chunked, import url, password, touch, view; tasks create/change/download/cancel/delete
- [x] Multi-output results zipped; `resultItems` list
- [x] Tool registry `app/tools/registry.py` with catalog metadata (slug, type, title, category, accepted files, options)

### Phase 2 — Front-end shell & design system
- [x] Design tokens, light/dark, responsive layout, original logo (SVG)
- [x] Home page: tool grid by category + search
- [x] Generic tool page: drop zone, file list, "More options", submit, result panel (poll, download, preview, start over, continue with another tool)
- [x] Upload client: progress, chunked for >5 MB, link import, per-file password prompt
- [x] Footer pages: about, privacy, terms, help

### Phase 3 — Organize tools
- [x] merge, split (pages / every N), split by bookmarks, split by size, split by text, split down the middle
- [x] alternate mix, extract pages, delete pages, organize/combine-reorder, rotate pages
- [x] Thumbnail page picker (select, rotate, reorder, delete) for organize/rotate/delete/extract/split

### Phase 4 — Modify tools
- [x] compress, crop (manual + auto), resize, n-up, flip, grayscale, deskew, flatten, repair
- [x] watermark (text + image), header/footer, page numbers, Bates numbering
- [x] edit metadata, bookmarks editor, delete annotations, rename by text
- [x] encrypt, unlock

### Phase 5 — Convert tools
- [x] pdf→jpg/png/tiff, jpg→pdf, extract images, extract text
- [x] pdf→excel/csv, pdf→word, pdf→ppt
- [x] word→pdf (LibreOffice), html→pdf (Playwright), OCR (OCRmyPDF/Tesseract)

### Phase 6 — PDF editor, forms, sign
- [ ] Editor page: PDF.js pages, toolbar (text, edit text, image, whiteout, shapes, line/arrow, draw, highlight/strike/underline, link, form fields, sign, insert/delete/rotate page, undo)
- [ ] Server `edit` handler applying all operation arrays
- [ ] Fill forms (`formValues`), create form fields, signatures (draw/type/upload)
- [ ] Local crash recovery (IndexedDB)

### Phase 7 — Platform extras
- [ ] Workflows (record → replay tool chains, stored in IndexedDB)
- [ ] Recent files panel, "continue with another tool"
- [ ] Rate-limit UI (remaining tasks, countdown)

### Phase 8 — Quality & deploy
- [ ] Full test suite green; sample PDFs generated in tests
- [ ] Dockerfile + docker-compose; production notes
- [ ] Security pass (upload size/type limits, SSRF, path traversal, signature checks, CSP headers)

---

## 4. Definition of done (per task)
1. Code + test written, `pytest` passes.
2. sejedarules.md updated (what changed, how it works).
3. plan.md checkbox ticked.
4. Commit + push to `origin main`.
