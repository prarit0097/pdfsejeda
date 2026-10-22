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

A web app with 43 registered PDF tools (merge, split, compress, convert, edit, sign, …). Each tool is its own server-rendered page. The browser uploads files, collects options, and shows previews; **all PDF processing happens on the server** (the editor renders in the browser but the save is a server task), exactly like sejda.com.

## 3. Tech stack

Python + FastAPI + Jinja2 templates + vanilla JS + self-hosted PDF.js 6.4.299 (ES modules, worker, CMaps, standard fonts and WASM codecs). PDF work uses pikepdf, pypdf, pypdfium2, reportlab, pdfplumber, Pillow, numpy, python-docx/pptx, openpyxl. Optional system tools: LibreOffice, Tesseract, Playwright Chromium. Full table and reasons: plan.md §1.

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
tests/               pytest suite (unit + API, run with `pytest -q`)
scripts/smoke_test.py  live end-to-end check of every tool against a running server
research/            reverse-engineering notes (input, not shipped)
plan.md              build plan
sejedarules.md       this file
```

## 5. Request flow (end to end)

1. **Upload.** `POST /api/files/upload` (multipart field `file`) → `{"id": "<fileId>"}`. Big files go through `POST /api/files/upload-chunked` in 5 MB chunks. Links: `POST /api/files {"url": …}`.
2. **Task.** `POST /api/tasks` with JSON `{type, files:[fileIds], …options}` → response body is the task id as a JSON string, plus headers `x-ratelimit-remaining`, `x-ratelimit-wait`. Errors: `400` (text), `402` `{reason, code}` when the hourly quota is used, `429`.
3. **Poll.** `GET /api/tasks/<id>/change` every 3 s → `{status, type, remark, resultFilename, resultFileSize, resultFullUrlPattern, warnings, resultItems, id, failureReason?}`. Status is one of `Queued`, `Processing`, `Completed`, `Failed`.
4. **Download.** `resultFullUrlPattern` with `{{filename}}` filled in → `/api/tasks/<id>/download/<name>?s=web-<sig>&d=true`. `d=true` = attachment, `v=true` = inline preview.
5. **Cleanup.** Uploads expire after 2 hours since their last keep-alive; results expire 2 hours after completion (`FILE_TTL_SECONDS`). Expired entries are denied on lookup and physical deletion is periodic. Open tool pages extend upload lifetime every 10 minutes. `POST /api/tasks/<id>/cancel`, `DELETE /api/tasks/<id>`.

## 6. Tools (task types)

Format: `type` — `/page-slug` — key options — how it works. Every tool lives in `app/tools/<group>.py` and registers itself with `register(Tool(...))`; the tool page renders its options form from that registration.

**Organize** (`app/tools/organize.py`)
- `merge` — `/merge-pdf` — `outlinePolicy` (retain/discard/one_entry_each_doc/retain_as_one_entry), `tocPolicy` (none/file_names/doc_titles), `acroFormPolicy` (merge/merge_renaming/flatten/none), `blankPageIfOdd`, `normalizePageSizes`, `filenameFooter`, `outputFilename`, `rotations[]` per file. Images become A4 pages first. TOC pages get clickable links.
- `splitByPages` — `/split-pdf` — `splitMode` every/after/even/odd, `step`, `pages` (split *after* these), `specificResultFilenames[]`, `outputFilenamePattern` tokens `[BASENAME] [CURRENTPAGE] [FILENUMBER] [TIMESTAMP]`, `discardOutline`.
- `splitByBookmarks` — `/split-pdf-by-outline` — `bookmarksLevel` 1–3, `bookmarksExpression` (regex filter), `includePageAfter`. Files are named after the bookmark.
- `splitBySize` — `/split-pdf-by-size` — `size` + `sizeUnit` MB/KB. Greedy: grows each chunk while the real saved size fits.
- `splitByText` — `/split-pdf-by-text` — `area {x,y,width,height}` (PDF points, **top-left origin**, drawn on page 1 in the UI), `startsWith`. New file whenever the text in the area changes; files are named after the text.
- `splitDownTheMiddle` — `/split-pdf-down-the-middle` — `mode` auto/vertical/horizontal, `ratio`, `excludedPages`, `autoDetectExcludedPages`, `rightToLeft`, `repagination` (booklet order). Works by duplicating each page and setting two CropBoxes.
- `alternateMix` — `/alternate-mix-pdf` — per-source `step[]`, `reverse[]`, `rotations[]` (also accepts `step`, `reverse`, `rotations` lists). Scalar step applies to all sources; legacy scalar reverse applies after the first. UI has individual overrides plus global defaults. Positive integer steps and quarter-turn rotations are validated; trailing pages are preserved. ≥2 files.
- `extractPages` — `/extract-pdf-pages` — `pages`, `discardOutline`.
- `deletePages` — `/delete-pdf-pages` — `pages`, `discardOutline`. Refuses to delete every page.
- `combineReorder` — `/organize-pdf` — `filePages ["fileIdx:page:rot"]` in final order, `"-1:-1:rot"` = blank page, `outputFilename`. Without `filePages`: all pages of all files.
- `rotatePages` — `/rotate-pdf-pages` — `pageRotationsPerSource ["fileIdx:page:deg"]` (per page, wins) or `rotation` + `pages` (bulk). Rotation is added to the existing /Rotate.

**Optimize & layout** (`app/tools/modify.py`)
- `compress` — `/compress-pdf` — `imageQuality` 0.65/0.8/1 (JPEG q 55/72/90), `imageDpi` (downsample above it, estimated from page size), `imageConversion` grayscale, `discardMultimedia`. Re-encodes each image only if smaller, drops unused resources, saves with object streams. Returns the original when compression cannot reduce size; `failIfOutputSizeNotReduced=true` instead fails clearly when output is not strictly smaller.
- `crop` — `/crop-pdf` — `cropMode` auto (render with PDFium, find non-white bbox, union over pages if `sameForAllPages`) / margins (`unit` + 4 margins) / area (drawn on a selected page). `cropScope` all/individual/odd-even with `cropAreas` keyed by 1-based page number or odd/even; unmarked individual/group pages keep their size. Regions use displayed top-left PDF points, are checked for finite positive dimensions, and honor selected `pages`. Sets CropBox and MediaBox.
- `resizePages` — `/resize-pdf` — `pageSize` (a1–a6, letter, legal, tabloid, ledger, executive, custom, original = keep size + margins), margins in `unit`. Content is scaled into the new page.
- `nup` — `/n-up-pdf` — `n` 2/4/8/16/32, `pageOrdering`, `preservePageSize`, `rightToLeft`.
- `flip` — `/flip-pdf` — `flipMode` horizontal/vertical, done with a `cm` matrix in displayed space.
- `grayscale` — `/grayscale-pdf` — `textConversion` grayscale/black, `imageConversion`, `compressImages`. Rewrites colour operators (rg/RG/k/K/sc/scn, colour spaces) in page and form content streams; images re-encoded as gray JPEG. Patterns/shadings are left as they are.
- `deskew` — `/deskew-pdf` — `onlyStronglySkewed`, `pages`, optional manual `angles {page: deg}`. Angle found by projection-profile variance on a PDFium render (−10°…10°), applied as a rotation around the page centre.
- `flatten` — `/flatten-pdf` — `flattenMode` onlyforms (generate appearances, flatten widgets, drop AcroForm) / all (rasterize each page at `resolution` dpi).
- `repair` — `/repair-pdf` — qpdf recovery first, pypdf page-by-page salvage second.

**Stamp & number** (`app/tools/stamp.py`)
- `headerFooter` — `/header-footer-pdf` and `pageNumbers` — `/page-numbers-pdf` — `pattern` tokens `[PAGE_ARABIC] [PAGE_ROMAN] [TOTAL_PAGES_ARABIC] [BASE_NAME] [FILE_NAME] [DATE]`, `pageLocation` (6 spots), `font`, `fontSize`, `color`, `pages`, `pageCountStartFrom`, `addMargins` (shrinks content to make room).
- `batesNumbering` — `/bates-numbering-pdf` — `style` presets or custom `pattern` with `[BATES_NUMBER] [FILE_NUMBER] [PAGE_ARABIC] [CASE]`, `batesStartFrom`, `batesDigits`, `batesIncrement`, `fileCountStartFrom`. Numbering continues across files.
- `watermark` — `/watermark-pdf` — `watermarkType` text/image (the image is uploaded alongside the PDFs), `opacity`, `rotation`, `pageLocation` center/top/bottom/tile, `layer` over/under, `fontSize`, `color`, `pages`.

**Security & document** (`app/tools/security_tools.py`)
- `encrypt` — `/encrypt-pdf` — `userPassword`, optional `restrictPermissions` + `ownerPassword` + `permissions[]`, `encryptionAlgorithm` aes_256 (R6) / aes_128 (R4) / rc4_128 (R3).
- `decrypt` — `/unlock-pdf` — the password is set with `POST /api/files/<id>/password` before the task; the file is saved without encryption.
- `editMetadata` — `/edit-pdf-metadata` — `metadata.Title|Author|Subject|Keywords|Creator|Producer|CreationDate|ModDate`, `removeAllMetadata`. The page pre-fills fields from `GET /api/files/<id>/metadata`. Stale XMP is removed so readers show the new values.
- `editBookmarks` — `/pdf-bookmarks` — `bookmarks` text (“Title | page”, two-space indent per level) or `jsonData` tree. Pre-filled from `GET /api/files/<id>/outline`.
- `deleteAnnotations` — `/delete-pdf-annotations` — `annotationTypes` (all or one type), `pages`. Form widgets are never removed.
- `renameByText` — `/rename-pdf` — `area` (drawn on page 1) + `renamePattern` tokens `[TEXT] [BASENAME] [FILENUMBER] [DATE]`.

**Convert** (`app/tools/convert.py`)
- `pdfToImage` — `/pdf-to-jpg` — `pages`/`allPages`, `imageFormat` jpg/png/tiff, `resolution` dpi, `imageColorType` rgb/grayscale/black_white, `tiffSingleFileWithAllPages`. Rendered with PDFium.
- `jpgToPdf` — `/jpg-to-pdf` — `pageSize` auto/a4/…/custom, `pageOrientation`, `pageMargin` none/small/big, `rotations[]` per file, `mergeOutputs`.
- `extractImages` — `/extract-images-from-pdf` — every distinct image XObject in its native format (JPEG stays JPEG), tiny images skipped.
- `extractText` — `/extract-text-from-pdf` — PDFium text per page, `pageBreaks` adds form feeds.
- `pdfToExcelNext` — `/pdf-to-excel` — pdfplumber table detection (ruled lines first, text alignment as fallback), `exportFormat` excel/csv, `singleSheet`. Numeric cells become numbers.
- `pdfToOfficeWord` — `/pdf-to-word` — pdfplumber words → lines → paragraphs; larger fonts become headings; tables become Word tables; pictures are cropped renders. Output .docx (python-docx).
- `pdfToPpt` — `/pdf-to-ppt` — one slide per page (page picture, slide size = page size), page text in speaker notes.
- `docToPdf` — `/word-to-pdf` — LibreOffice headless when installed (isolated profile per task); otherwise (or if the installed engine fails) a basic built-in DOCX/TXT renderer with a warning. Windows uses the console launcher and a short isolated temporary profile path, avoiding observed LibreOffice crashes with long paths. DOC/ODT/RTF require a working LibreOffice engine.
- `htmlToPdf` — `/html-to-pdf` — Playwright Chromium; `urls` (one per line), `htmlCode`, uploaded .html files; `pageSize`, `pageOrientation`, `viewportWidth`, `pageMargin`+units, `delay`, `usePrintMedia`. All HTTP(S) resources and redirect hops are resolved, validated and connected to pinned public IPs by HTTPX; proxy environment variables are ignored. Top-level redirects navigate to the validated final URL; redirected HTML/CSS retain relative asset bases. Service workers are blocked and WebSockets never connect to the network. Additional options: `lang`, `timezone`, `includeHeaderFooterDetails`, `hideNotices`, `blockAds`, `partialContentAllowed`. Ads/notices use bounded heuristics, not universal detection. US/EU browser hosting is not implemented.
- `ocr` — `/ocr-pdf` — Tesseract renders each page at 300 dpi and makes a text-only PDF layer (`textonly_pdf=1`) that is overlaid invisibly on the original page; `lang`, `outputFormats` pdf/txt.

**Editor** (`app/tools/editor.py`, `templates/editor.html`, `static/js/editor.js`, `static/css/editor.css`)
- Task types `edit` (`/pdf-editor`), `fillSign` (`/sign-pdf`), `editForms` (`/pdf-forms`) share one handler and one page; only the starting tool differs.
- **Browser side:** PDF.js renders pages lazily; objects (text, edited text, image/signature, box, circle, whiteout, line, arrow, freehand, highlight/strike/underline, link, form text box, checkbox, dropdown, listbox, radio) live in an overlay. Each object stores x, y, w, h in PDF points, top-left origin, in the page's displayed orientation. Existing form fields are shown as real inputs (from `page.getAnnotations()`); their values go to `formValues`. "Edit text" puts clickable spans over PDF.js text items; clicking one creates an `edittext` object (white box over the old text + new text). Page bar: rotate, delete, insert blank page. Undo stack (80 steps), Delete key, Esc. Signatures: draw / type (cursive Google fonts) / upload (white turned transparent), up to 4 remembered in localStorage. Drafts autosave to localStorage under a SHA-256 of document bytes; page-only changes recover too. Submission flushes pending drafts and only a completed save clears that saved revision. Expired/corrupt drafts are pruned on opening the editor. Find & replace locates adjacent horizontal PDF.js text runs, supports case matching, selected/all replacements and undo. Text replacement and whiteout are visual overlays: original text remains extractable; they are not redaction.
- **Wire format:** `pageOrder ["orig:rot" | "-1:rot"]` then operation arrays with **bottom-left** coordinates — see the docstring at the top of `editor.py`. Sejda-style `deletePageOperations` / `insertPageOperations` / `rotatePageOperations` are also accepted when `pageOrder` is absent.
- **Server side:** builds the page list, groups drawing ops per page and draws them in one `stamp()` per page (order: edited text, shapes, highlights, images, freehand, lines, new text); links become Link annotations (user-space rects); new text/checkbox/dropdown/listbox/radio fields get clipped appearance streams with rotated placement; choices accept export/display pairs and multiselect, radio fields share groups, text supports defaults/maxLength/comb, and required flags are preserved; `formValues` are filled with pypdf afterwards (checkbox/radio map to their real "on" state); `flattenForms` flattens at the end.
- `tool.js` exposes `Tool.submitBody(body, {onCompleted})`, `Tool.addFiles(files)`, `Tool.reset()` so the editor reuses the upload, result and recent-results flow. Events: `files-changed`, `editor-open`, `editor-close`.

**Workflows** (`templates/workflows.html`, `static/js/workflows.js`, recording in `tool.js`)
- Every successful task (except editor, organize, HTML→PDF) is remembered in sessionStorage `lastStep` as its task body without files. "Continue in another tool" appends it to sessionStorage `workflowChain` (max 10). Passwords and credentials are removed from recorded, imported and exported steps. Encryption workflows request passwords for each run; encrypted intermediate results are unlocked using in-memory values only. Browser-storage failures do not prevent processing. The result screen offers "Save as workflow", which stores `{id, name, created, steps[]}` in localStorage `workflows`.
- `/workflows` lists them (an example is shown when there are none), renames, deletes, exports/imports JSON (`format: pdfnova-workflows-v1`). Running: upload files → step 1 with those ids → wait → `POST /api/tasks/<id>/continue` → PDFs become the next step's files → … → the last task's normal result screen.

**Optional system tools** — detected at runtime by `find_binary()`: LibreOffice (`soffice`), Tesseract (`tesseract`), Playwright Chromium. Tools that need a missing one fail with a clear message instead of crashing.

**Shared building blocks** (`app/tools/`)
- `common.py` — open/save PDFs with passwords, page sizes, `output_name` (honours `outputFilenamePattern`).
- `draw.py` — `stamp()` draws with reportlab in *displayed* coordinates (after /Rotate) and merges onto a page; `place_page()` draws one page scaled into a rectangle of another (n-up, resize, normalize). Font picking (`font_for`) falls back to a Unicode TTF for non-Latin text.
- `outlines.py` — read/remap/write bookmarks across documents.
- `imaging.py` — image → PDF pages (Pillow + reportlab).

## 6a. Front end

- `templates/base.html` — header (logo, "All tools" mega menu, theme toggle), footer, SVG icon sprite (`_icons.html`).
- `templates/index.html` — hero, search, category chips, tool cards (filtering is client-side).
- `templates/tool.html` — generic tool page: drop zone (device / URL), file list, page thumbnails (`#pages-ui`), options (basic + "More options"), submit, result panel, recent results, how-to, FAQ, related tools.
- `static/js/site.js` — `window.UI`: theme, mega menu, toasts, modal dialogs, helpers.
- `static/js/tool.js` — `window.Tool`: uploads (simple ≤5 MB, chunked >5 MB, 3 parallel chunks, link import, password prompt), file reorder/rotate (merge), `show_if` conditional options, form → JSON, submit, 402 countdown, polling every 3 s, result screen (download, preview, ZIP items, continue in another tool, delete now), recent results in localStorage, keep-alive `touch` every 10 min, files handed over via sessionStorage `continueFiles`.
- `static/js/pages-ui.js` — PDF.js thumbnails; modes `select`, `rotate`, `organize`, `split`, `area`.
- `static/css/app.css` — design tokens (light/dark), all components.

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
| `MAX_QUEUED_TASKS` | `32` | maximum waiting tasks in addition to workers; overload returns 429 |
| `TASK_TIMEOUT_SECONDS` | `900` | cooperative running timeout; waiting tasks expire at the shorter timeout/TTL |
| `MAX_REQUEST_MB` | `64` | request-body cap outside file-upload endpoints |
| `TRUST_PROXY` | `0` | trust forwarded IP headers only behind a proxy that overwrites them |
| `ALLOW_PRIVATE_URLS` | `0` | dangerous opt-in for private URL access; keep off publicly |
| `NO_DOTENV` | unset | when set, skip loading local `.env` |

Settings can also live in a `.env` file in the repo root (`KEY=VALUE` lines, loaded by `app/config.py`; real environment variables win). `.env` is git-ignored; `.env.example` is the template. `docker-compose.yml` reads the same file via `env_file`. Tests set `NO_DOTENV=1` so they never read it.

## 7a. Deployment & security

- `Dockerfile` (python:3.12-slim + LibreOffice Writer, Tesseract with eng/hin/spa/fra/deu, Noto/DejaVu/Liberation fonts, Playwright Chromium), runs as a non-root user, data in volume `/data`. `docker-compose.yml` sets the env vars from §7 — **change `SECRET_KEY`**.
- Behind a proxy/CDN, set `TRUST_PROXY=1` only if the proxy overwrites forwarded client-IP headers and direct access is blocked; otherwise those headers can spoof the quota identity.
- Headers: CSP on HTML pages (self-hosted scripts/workers/codecs + optional Google Fonts; JavaScript eval remains blocked, WASM compilation is allowed), `X-Frame-Options: SAMEORIGIN` (except result downloads/previews so the preview iframe works), `nosniff`, `no-store` on the API.
- Upload size limit (`MAX_FILE_MB`), file ids validated by regex (no path traversal), URL import and HTML→PDF block private/loopback addresses on every redirect/request, download links signed with HMAC per task. Task IDs are 32 random characters from a 32-character alphabet (160 bits) plus a UTC timestamp. File IDs and task IDs are bearer capabilities: knowing an ID grants the corresponding access, including polling/continuing/deleting tasks. Signatures are not an independent ownership check. Upload endpoints cap size; tool submission checks allowed extensions/MIME and parsers validate content.


## 7b. Runtime limits and verification

- Jobs and per-IP quotas are process-local. Use one Uvicorn process; process restart invalidates task links even if files still exist on disk. Shared storage/Redis and account-based authorization are not implemented.
- Admission is bounded before file IO; validation errors release capacity and overload refunds hourly quota. Cancellation/timeouts are cooperative: a stuck native call retains its worker until it exits. Python threads cannot be forcibly killed. Partial failed results are cleaned, and partial continuation copies are rolled back. Aggregate disk quotas are not implemented.
- Metadata writes are atomic. Missing/corrupt upload records return not-found instead of server errors. Chunk uploads validate actual byte counts and merge received ranges, accepting retries without counting overlapping bytes twice.
- PDFium calls must not run concurrently across threads. `pdfium_doc()` serializes their document lifetime with a process-wide reentrant lock, and queue-triggered garbage collection uses that lock. Other tools can still run concurrently. Callers must close native children and not retain live PDFium objects beyond the helper's scope.
- `/result?id=TASK_ID` reopens a live task through its tool page; unavailable tasks show an expiry page. `/developers`, `/html-pdf-api`, `/api/docs` and `/api/tools` describe this installation's actual API.
- `requirements-lock.txt` records the tested clean Windows/Python 3.13 environment, including optional Chromium tooling; `requirements-test.txt` installs test extras. Docker was reviewed and browser paths fixed, but a Docker build remains unverified because this workstation has no Docker CLI.
- Reproduce tests with `pytest -q`, `scripts/smoke_test.py`, `scripts/browser_regression.py`, and `scripts/editor_regression.py`. Full details and exact remaining parity gaps are in [research/audit-2026-10-22/REPORT.md](research/audit-2026-10-22/REPORT.md). Phase checkboxes record implemented work, not a claim of complete Sejda parity.

## 8. Change log

Newest first. One line per change: date — what — where.

- 2026-10-22 — Fresh REA evidence, clean-install verification, dependency snapshot, browser/API regression scripts, developer guides and result reopening — `research/audit-2026-10-22/`, `scripts/`, `requirements-lock.txt`, `app/web.py`, templates
- 2026-10-22 — Bounded queue, 160-bit task capabilities, quota refunds, atomic metadata, chunk/expiry/cancellation/continuation regressions and PDFium serialization — platform modules, `tools/common.py`, platform tests
- 2026-10-22 — Fix Windows LibreOffice profile crash; pin HTML resources and redirects, preserve relative assets/final URL, block network WebSockets, add print options; strict compression and Docker browser path — `tools/convert.py`, `modify.py`, conversion tests, `Dockerfile`
- 2026-10-22 — Self-host PDF.js 6.4.299, advanced form creation/filling, success-only draft cleanup, SHA-256 recovery, workflow credential prompts, find/replace and active mobile editor improvements — editor JS/templates/CSS, `tools/editor.py`, editor tests
- 2026-10-22 — Individual/odd-even crop drawing and per-source alternate mix options with output verification — `tools/modify.py`, `organize.py`, `pages-ui.js`, `tool.js`, crop/mix tests

- 2026-10-22 — `.env` support (+ `.env.example`, compose `env_file`), live smoke test of all tools over HTTP — `app/config.py`, `scripts/smoke_test.py`, `docker-compose.yml`
- 2026-10-22 — Phase 7–8: workflows (record from "continue in another tool", save, run, import/export), CSP header, Dockerfile + docker-compose + .dockerignore, README run/deploy notes — `app/static/js/workflows.js`, `app/templates/workflows.html`, `app/static/js/tool.js`, `app/main.py`, `Dockerfile`
- 2026-10-22 — Phase 6: PDF editor / fill & sign / create forms — server handler with pageOrder + 10 operation types + form creation and filling; browser editor with toolbar, overlay objects, edit existing text, signatures, form inputs, page actions, undo, drafts; `tool.js` exposes submitBody/addFiles/reset; aliases pdfToDoc→pdfToOfficeWord, pdfToExcel→pdfToExcelNext — `app/tools/editor.py`, `app/templates/editor.html`, `app/static/js/editor.js`, `app/static/css/editor.css`
- 2026-10-22 — Phase 5: PDF→JPG/PNG/TIFF, JPG→PDF, extract images, PDF→text, PDF→Excel/CSV, PDF→Word, PDF→PowerPoint, Word→PDF (LibreOffice + fallback), HTML→PDF (Playwright), OCR (Tesseract text layer) — `app/tools/convert.py`, `tests/test_convert.py`
- 2026-10-22 — Phase 4: compress, crop, resize, n-up, flip, grayscale, deskew, flatten, repair, header/footer, page numbers, Bates, watermark, encrypt, unlock, metadata, bookmarks, delete annotations, rename by text; `/api/files/<id>/outline` and `/metadata`; 38 tests — `app/tools/modify.py`, `stamp.py`, `security_tools.py`
- 2026-10-22 — Phase 1–3: platform core (config, FileStore, JobQueue, page parser, HMAC links, SSRF-safe URL import, per-IP quota), full `/api` (upload, chunked upload, URL import, password, touch, view, tasks, change, download, cancel, delete, continue, tools), UI (design system, home, generic tool page, thumbnails), 11 organize tools, 21 tests — `app/`, `tests/`
- 2026-10-22 — Project started: plan.md and sejedarules.md written; Python/FastAPI stack chosen — `plan.md`, `sejedarules.md`
