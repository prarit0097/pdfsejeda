# sejedarules.md — how this app works (living document)

**Read this first.** Every change in this repo, small or large, is recorded here so anyone can understand how the app works without reading all the code. If you change code, update this file in the same commit.

---

## 1. Ground rules

1. **Plan first, then build.** The full plan is in [plan.md](plan.md). Work follows its phases in order; tick the checkbox there when a task is done.
2. **Log everything here.** Every change gets an entry in §8 "Change log" and, if it changes behaviour, an update to the relevant section below.
3. **Push after every unit of work** to https://github.com/prarit0097/pdfsejeda (`main`).
4. **Behaviour comes from the research.** [research/SEJDA.md](research/SEJDA.md) describes how sejda.com works. We replicate the *behaviour* (tools, options, API flow, editor model).
5. **Do not copy Sejda's brand or code.** No Sejda name, logo, page text, or shipped/obfuscated JS. Our branding (default name `PDFNova`, set with `APP_NAME`) and our page copy are original.
6. **Licences:** only permissive dependencies (MIT/BSD/Apache/MPL). No AGPL (no PyMuPDF, Ghostscript, Sejda SDK).
7. **Every tool has a test.** `pytest` must pass before pushing.
8. **Security defaults stay on:** size/type limits, SSRF-safe URL import, HMAC-signed download links, 2-hour file expiry.

---

## 2. What the app is

A web app with ~45 PDF tools (merge, split, compress, convert, edit, sign, …). Each tool is its own server-rendered page. The browser uploads files, collects options, and shows previews; **all PDF processing happens on the server** (the editor renders in the browser but the save is a server task), exactly like sejda.com.

## 3. Tech stack

Python + FastAPI + Jinja2 templates + vanilla JS + PDF.js. PDF work uses pikepdf, pypdf, pypdfium2, reportlab, pdfplumber, Pillow, numpy, python-docx/pptx, openpyxl. Optional system tools: LibreOffice, Tesseract/OCRmyPDF, Playwright Chromium. Full table and reasons: plan.md §1.

## 4. Repo layout

```
app/
  main.py            FastAPI app: mounts static, page routes, API routes
  config.py          settings from environment variables
  storage.py         FileStore — uploaded files + results on disk, TTL expiry
  jobs.py            JobQueue + Task model (status machine, cancel)
  pages.py           page-selection parser ("1-3,7", odd, even, "5-")
  security.py        download-link signatures, safe URL fetching
  ratelimit.py       per-IP tasks-per-hour quota
  api.py             /api/* routes
  web.py             HTML page routes
  tools/             one module per tool group; registry maps task type → handler
  templates/         Jinja2 pages
  static/            css, js, images
tests/               pytest suite
research/            reverse-engineering notes (input, not shipped)
plan.md              build plan
sejedarules.md       this file
```

## 5. Request flow (end to end)

1. **Upload.** `POST /api/files/upload` (multipart field `file`) → `{"id": "<fileId>"}`. Big files go through `POST /api/files/upload-chunked` in 5 MB chunks. Links: `POST /api/files {"url": …}`.
2. **Task.** `POST /api/tasks` with JSON `{type, files:[fileIds], …options}` → response body is the task id as a JSON string, plus headers `x-ratelimit-remaining`, `x-ratelimit-wait`. Errors: `400` (text), `402` `{reason, code}` when the hourly quota is used, `429`.
3. **Poll.** `GET /api/tasks/<id>/change` every 3 s → `{status, type, remark, resultFilename, resultFileSize, resultFullUrlPattern, warnings, resultItems, id, failureReason?}`. Status is one of `Queued`, `Processing`, `Completed`, `Failed`.
4. **Download.** `resultFullUrlPattern` with `{{filename}}` filled in → `/api/tasks/<id>/download/<name>?s=web-<sig>&d=true`. `d=true` = attachment, `v=true` = inline preview.
5. **Cleanup.** Files and results expire after 2 hours (`FILE_TTL_SECONDS`). `POST /api/tasks/<id>/cancel`, `DELETE /api/tasks/<id>`.

## 6. Tools (task types)

Filled in as tools are implemented. Format: `type` — page slug — options — implementation.

_(none yet)_

## 7. Configuration

| Env var | Default | Meaning |
|---|---|---|
| `APP_NAME` | `PDFNova` | brand name shown in the UI |
| `DATA_DIR` | `./data` | where uploads and results live |
| `FILE_TTL_SECONDS` | `7200` | file and result lifetime (2 h) |
| `MAX_FILE_MB` | `200` | per-file upload limit |
| `TASKS_PER_HOUR` | `0` | free tasks per IP per hour; `0` = unlimited |
| `SECRET_KEY` | random per process | signs download links; set it in production |
| `WORKERS` | `4` | parallel task threads |

## 8. Change log

Newest first. One line per change: date — what — where.

- 2026-10-22 — Project started: plan.md and sejedarules.md written; Python/FastAPI stack chosen — `plan.md`, `sejedarules.md`
