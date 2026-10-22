# PDFNova / pdfsejeda — project guide, architecture and working rules

**Read this first.** This is the main project handover document for the owner, contributors and coding agents. It explains what the app is, why it exists, what is included, how it was built, how to run and test it, and the rules for changing it. Read it before modifying the project. Update affected sections and §8 in the same commit whenever implementation or scope changes.

**Last documentation review:** 2026-10-22. Descriptions below refer to the checked-in implementation. Historical verification results are dated, not a promise that later code has been tested.

| Project identity | Value |
|---|---|
| Product/display name | **PDFNova** by default; configurable through `APP_NAME` |
| Repository/project name | **pdfsejeda** |
| Local workspace used for development | `E:\coding\Sejda copy` — a local folder name, not a runtime dependency |
| Git repository | https://github.com/prarit0097/pdfsejeda |
| Git remote and main branch | `origin`, `main` |
| Application entry point | `app.main:app` |
| Default local address | `http://127.0.0.1:8000` |
| Implementation | Python/FastAPI backend; Jinja2, vanilla JavaScript and PDF.js frontend |
| Current registered tools | **43** distinct tool pages; API aliases do not add to this count |
| Functional reference | Public Sejda behavior captured in the local `research/` documents |

## Contents

- [1. Ground rules](#1-ground-rules)
- [2. What the app is, why it exists and current scope](#2-what-the-app-is)
- [3. Tech stack and design decisions](#3-tech-stack)
- [4. Repo layout](#4-repo-layout)
- [5. Request flow and API routes](#5-request-flow-end-to-end)
- [6. All tools, editor, workflows and frontend](#6-tools-task-types)
- [7. Configuration, setup, deployment, security, testing and maintenance](#7-configuration)
- [8. Change log](#8-change-log)

---

## 1. Ground rules

1. **Plan first, then build.** The full plan is in [plan.md](plan.md). Work follows its phases in order; tick the checkbox there when a task is done.
2. **Log everything here.** Every change gets an entry in §8 "Change log" and, if it changes behaviour, an update to the relevant section below.
3. **Push after every unit of work** to https://github.com/prarit0097/pdfsejeda (`main`).
4. **Behaviour comes from the research.** [research/SEJDA.md](research/SEJDA.md) describes how sejda.com works. We replicate the *behaviour* (tools, options, API flow, editor model).
5. **Do not ship copied Sejda branding or application code.** Product-facing name/logo/page copy and application code are original. Research documents may name and cite the reference service. Our default product name is `PDFNova`, set with `APP_NAME`; shipped/obfuscated Sejda JS does not belong in the app.
6. **Licences:** only permissive dependencies (MIT/BSD/Apache/MPL). No AGPL (no PyMuPDF, Ghostscript, Sejda SDK).
7. **Every tool has a test.** `pytest` must pass before pushing.
8. **Security defaults stay on:** size/type limits, SSRF-safe URL import, HMAC-signed download links, 2-hour file expiry.
9. **Preserve existing work.** Inspect `git status` before editing. Do not discard unrelated changes, reset the branch, overwrite an existing `.env`, or delete user data to make a test pass.
10. **Separate facts from goals.** Mark implemented, verified, unverified, remaining and deliberately deferred work accurately. A checked plan item or a rendered page alone does not prove exact feature parity or correct PDF output.
11. **Keep private material out of Git.** Never commit real passwords, `.env`, uploaded documents, result files, virtual environments or raw browser evidence containing tokens. Use generated fixtures for tests; preserve third-party notices and vendored-asset provenance.
12. **Change only the authorized scope.** New external integrations, outbound email, accounts and payments must not be silently enabled. The current exclusions below remain in force until the user changes them.

**Current scope (user clarification, 2026-10-22):** accounts/billing, cloud integrations and email signing are deferred. Do not implement them or count their absence as a blocker for the current PDF-tool delivery. Local PDF signing (draw/type/upload signatures), password protection, URL import and local workflows remain in scope.

---

## 2. What the app is

A browser-based PDF toolkit with 43 registered tools: merge, split, compress, convert, edit, fill forms, sign, OCR, secure and organize documents. It runs on a local computer or a separately hosted server. Each tool has its own server-rendered page, and no account is required for the implemented tool flow.

Typical use: upload a PDF, choose pages/options, run the tool, then download or preview the output. Multiple outputs are offered as a ZIP and individual files. A result can continue into another tool; repeated chains can be saved as local workflows.

The browser handles previews, interactions, signature drawing, image preparation and editor drafts. **Final document operations and output generation run on the server.** Uploads are therefore sent to the machine hosting this app; this is not a browser-only/offline PDF processor.

### 2.1 Why this app exists

The owner's goal is a working Sejda-style PDF application with closely matching tool capabilities, options and workflows, built in this repository and maintainable without proprietary Sejda code. It brings routine PDF tasks into one interface and supports running that interface on infrastructure controlled by the owner.

The implementation uses original PDFNova branding and copy. Behavioral research guides reconstruction, while the source code and tests establish what this app actually does. Exact visual parity, every advanced option and every document-conversion edge case have not been established; do not describe the current build as a complete Sejda service clone.

### 2.2 Included and deferred scope

| Included now | Meaning |
|---|---|
| Core PDF tools and editor | The 43 tools in §6, including form creation/filling and visual text editing |
| Local PDF signatures | Draw, type or upload a signature and place it on the document; this is a visual signature, not a certificate-based digital-signature service |
| File input | Local uploads, chunked uploads and public URL import |
| Results and automation | Download, preview, continue to another tool, local saved workflows |
| Interface | Tool search/categories, light/dark theme, desktop/mobile interactions, help and developer guides |
| Operational work | Validation, expiry, job limits, security fixes and appropriate regression tests |

**Deferred by the user:** accounts/billing, cloud integrations and email signing. These are not current delivery blockers. In particular, cloud OAuth pickers/export and email signature-request flows are not required for this scope. Public URL import and ordinary local PDF signatures remain included.

Other remaining work, such as translations, a native desktop distribution, exact visual parity and advanced PDF controls, is listed in §7.7 and `plan.md`. Deferral is a scope decision, not a claim that the feature already exists.

## 3. Tech stack

Python is the requested implementation language. The project uses a small server-rendered architecture so it can run without a JavaScript application framework or frontend build pipeline.

| Component | Used for | Why this choice |
|---|---|---|
| Python 3.12+; FastAPI/Uvicorn | HTTP API, HTML routes, application startup | One backend can serve pages and document tasks |
| Jinja2 + vanilla JS + CSS | Pages, upload/result UI, theme, editor interactions | No React/Node build step is required to run the app |
| Self-hosted PDF.js 6.4.299 | Browser page/text/form previews | Local renderer, worker, CMaps, standard fonts and WASM codecs avoid a preview-CDN dependency |
| pikepdf/qpdf + pypdf | PDF structure, page edits, encryption, forms, outlines | Complementary structural and document-model operations |
| pypdfium2/PDFium | Rendering, text extraction, image-based operations | Shared native rendering engine, serialized as described in §7.4 |
| ReportLab | Text, shapes, stamps, overlays and fallback document generation | Reusable PDF drawing primitives |
| pdfplumber | Words, layout and table detection | Supports Word/Excel reconstruction and text-based tools |
| Pillow + NumPy | Image handling, compression, crop/deskew analysis | Pixel and image processing |
| python-docx, python-pptx, openpyxl | DOCX, PPTX and XLSX output | Native Office file generation |
| fonttools + uharfbuzz | Font fallback and complex-script shaping | Improves mixed-script output when suitable fonts are installed |
| LibreOffice, Tesseract, Playwright Chromium | Office conversion, OCR, HTML printing | Optional external engines; included in the Docker recipe |
| ThreadPoolExecutor + local disk/JSON | Jobs, uploads, results and metadata | Simple single-process deployment with bounded admission |
| pytest + HTTPX + Playwright | Unit/API, live HTTP and real-browser verification | Tests can inspect actual generated/downloaded documents |

There is currently no Redis queue, SQL application database, shared object store or account system. Tasks and quotas live in memory; file bytes and upload metadata live on disk. Saved workflows/drafts live in the browser. Exact dependency snapshots and notices are in `requirements-lock.txt` and `THIRD_PARTY_NOTICES.md`. Stack decisions are also recorded in `plan.md` §1.

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
  tools/             registry.py + organize/modify/stamp/security_tools/convert/editor
                     shared helpers: common.py, draw.py, imaging.py, outlines.py
  templates/         Jinja2 pages
  static/            css, js, images; vendor/pdfjs holds the pinned preview assets
tests/               pytest suite (unit + API, run with `pytest -q`)
scripts/smoke_test.py  live end-to-end check of every tool against a running server
scripts/browser_regression.py      generic UI, downloads, mobile layout and tool controls
scripts/editor_regression.py       editor/forms/workflows and active mobile touch checks
scripts/concurrency_regression.py  simultaneous jobs with output validation
research/            reverse-engineering notes (input, not shipped)
  audit-2026-10-22/   evidence summaries, verification.json and the parity REPORT.md
data/                default runtime uploads/results; git-ignored
data-*/              local QA artifacts/fixtures/screenshots; git-ignored
.venv/               local Python environment; git-ignored
.env                 local secrets/settings; git-ignored
.env.example         public configuration example, with no real secrets
requirements.txt     supported Python dependency ranges
requirements-test.txt  requirements + optional Playwright testing dependency
requirements-lock.txt  exact tested Python dependency snapshot
Dockerfile           image recipe with PDF engines and fonts
docker-compose.yml   single service + persistent named data volume
deploy/hostinger/    isolated shared-server Compose/env/proxy examples and runbook
THIRD_PARTY_NOTICES.md  vendored asset provenance and license pointers
README.md            short setup entry point
plan.md              build plan
sejedarules.md       this file
```

`app/main.py` creates the app and mounts static/API/page routers. `app/web.py` selects templates. `app/api.py` validates requests and hands tasks to `JobQueue`. `app/tools/registry.py` maps each task type to its handler and exposes metadata used to render tool options. `app/tools/__init__.py` is not the application entry point.

## 5. Request flow (end to end)

1. **Upload.** `POST /api/files/upload` (multipart field `file`) returns file info including `id`, `name`, `size`, `pages` and `passwordProtected`. Big files go through `POST /api/files/upload-chunked` in 5 MB chunks. Links: `POST /api/files {"url": …}`.
2. **Task.** `POST /api/tasks` with JSON `{type, files:[fileIds], …options}` → response body is the task id as a JSON string, plus headers `x-ratelimit-remaining`, `x-ratelimit-wait`. Errors: `400` (text), `402` `{reason, code}` when the hourly quota is used, `429`.
3. **Poll.** `GET /api/tasks/<id>/change` every 3 s → `{status, type, remark, resultFilename, resultFileSize, resultFullUrlPattern, warnings, resultItems, id, failureReason?}`. Status is one of `Queued`, `Processing`, `Completed`, `Failed`.
4. **Download.** `resultFullUrlPattern` with `{{filename}}` filled in → `/api/tasks/<id>/download/<name>?s=web-<sig>&d=true`. `d=true` = attachment, `v=true` = inline preview.
5. **Cleanup.** Uploads expire after 2 hours since their last keep-alive; results expire 2 hours after completion (`FILE_TTL_SECONDS`). Expired entries are denied on lookup and physical deletion is periodic. Open tool pages extend upload lifetime every 10 minutes. `POST /api/tasks/<id>/cancel`, `DELETE /api/tasks/<id>`.

### 5.1 Architecture and storage lifecycle

```text
Browser tool/editor page
  -> upload file / import public URL
  -> FileStore: DATA_DIR/uploads/<fileId>/data + meta.json
  -> POST task type + file IDs + options/editor operations
  -> bounded JobQueue -> registered tool handler
  -> DATA_DIR/results/<taskId>/... (+ temporary <taskId>.work)
  -> status polling -> download/preview/ZIP
  -> optional continue: result files copied into new upload records
```

Task state is `Queued -> Processing -> Completed | Failed`. Cancellation is exposed as `Failed` with a cancellation reason, rather than a separate public `Cancelled` status. Timeouts are cooperative and do not kill a running Python/native thread. The queue holds at most `WORKERS + MAX_QUEUED_TASKS` admitted running/waiting jobs. Existing task records remain available until their result TTL expires.

`StoredFile` metadata includes the sanitized filename, MIME, size, timestamps, optional source URL and optional PDF password. Passwords needed to reopen uploaded PDFs are stored with upload metadata until deletion; this metadata is not encrypted at rest. Do not commit it or log it. Metadata replacement is atomic.

`TaskContext` gives handlers input paths, output/temp directories, option helpers, warnings, status remarks and cancellation checks. Results are packaged after the handler finishes. The sweeper runs at an interval between 1 and 300 seconds, based on the configured TTL; filesystem deletion may lag expiry and is retried when an open file prevents deletion.

Failed-task partial results and temporary work directories are cleaned. If continuing a result fails after some upload copies were created, those partial copies are rolled back. Chunk tracking merges byte ranges so overlapping retries are not counted twice. Missing/corrupt upload metadata or missing bytes are reported as unavailable files.

### 5.2 Page and API reference

| Method/path | Purpose |
|---|---|
| `GET /` | Tool catalog, search and category filters |
| `GET /<tool-slug>` | One of the 43 registered tool pages |
| `GET /workflows` | Saved workflow management and execution |
| `GET /result?id=<taskId>` | Redirect to the live task's tool/result screen; unavailable tasks show an expiry page |
| `GET /about`, `/help`, `/privacy`, `/terms` | Product/help/privacy pages |
| `GET /developers`, `/html-pdf-api` | Guides to the actual local API |
| `GET /api/docs`, `/openapi.json` | Interactive OpenAPI reference and schema |
| `GET /api/tools` | Current registered types, slugs, accepted formats and option metadata |
| `POST /api/files/upload-check` | Upload availability check |
| `POST /api/files/upload` | Multipart upload using field `file` |
| `POST /api/files/upload-chunked` | Chunk upload with `Content-Range`, `X-Upload-Id`, `X-File-Name` |
| `POST /api/files` | Register/download a public URL |
| `GET /api/files/<id>` | Upload information |
| `GET /api/files/<id>/view` | File bytes for preview; active web content is served as a download |
| `GET /api/files/<id>/metadata` | Read PDF metadata for the UI |
| `GET /api/files/<id>/outline` | Read PDF bookmarks for the UI |
| `POST /api/files/<id>/password` | Validate/store the PDF opening password |
| `POST /api/files/<id>/touch` | Extend upload keep-alive lifetime |
| `POST /api/tasks` | Submit `{type, files, ...options}`; successful body is a JSON task-ID string |
| `GET /api/tasks/<id>/change` | Poll task state and result information |
| `GET /api/tasks/<id>/download/<filename>` | Signed result download/preview |
| `POST /api/tasks/<id>/continue` | Register result files as new uploads |
| `POST /api/tasks/<id>/cancel` | Request cancellation |
| `DELETE /api/tasks/<id>` | Delete task/result records and request cancellation if running |

Common errors: `400` invalid input, `402` enabled hourly quota exhausted, `403` invalid download signature, `404` missing/expired data, `413` body/file too large, `429` queue capacity exceeded. Framework parameter validation can return `422`. Some tool errors are detected during processing and appear as a `Failed` task, not as a failed submission response.

Download URL patterns contain host/path without a scheme and an encoded `%7B%7Bfilename%7D%7D` placeholder. Add the deployment's scheme and replace that placeholder with the URL-encoded result filename. Preserve `s=...`; use `d=true` for attachment or `v=true` for supported inline previews. Treat file IDs, task IDs and signed links as private access credentials.

## 6. Tools (task types)

Format: `type` — `/page-slug` — key options — how it works. Every tool lives in `app/tools/<group>.py` and registers itself with `register(Tool(...))`; the tool page renders its options form from that registration.

The API also accepts `pdfToDoc` as an alias for `pdfToOfficeWord`, and `pdfToExcel` for `pdfToExcelNext`. `/api/tools` is the machine-readable current catalog; aliases share an existing tool and are not additional pages.

**Organize** (`app/tools/organize.py`)
- `merge` — `/merge-pdf` — `outlinePolicy` (retain/discard/one_entry_each_doc/retain_as_one_entry), `tocPolicy` (none/file_names/doc_titles), `acroFormPolicy` (merge/merge_renaming/flatten/none), `blankPageIfOdd`, `normalizePageSizes`, `filenameFooter`, `outputFilename`, `rotations[]` per file. Images become A4 pages first. TOC pages get clickable links.
- `splitByPages` — `/split-pdf` — `splitMode` every/after/even/odd, `step`, `pages` (split *after* these), `specificResultFilenames[]`, `outputFilenamePattern` tokens `[BASENAME] [CURRENTPAGE] [FILENUMBER] [TIMESTAMP]`, `discardOutline`.
- `splitByBookmarks` — `/split-pdf-by-outline` — `bookmarksLevel` 1–3, `bookmarksExpression` (regex filter), `includePageAfter`. Files are named after the bookmark.
- `splitBySize` — `/split-pdf-by-size` — `size` + `sizeUnit` MB/KB. Chooses the largest next chunk whose real saved size fits, using galloping/binary trial saves; warns when a single page already exceeds the limit.
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

**Optional system tools** — LibreOffice (`soffice`) and Tesseract (`tesseract`) are located by `find_binary()`; Playwright launches its installed Chromium. The app can start without these engines. Availability is established by actually running the relevant tool, not just by showing its page. Missing packages/engines produce task failures or supported fallbacks; browser-launch failures may require server-log inspection.

**Shared building blocks** (`app/tools/`)
- `common.py` — open/save PDFs with passwords, page sizes, `output_name` (honours `outputFilenamePattern`).
- `draw.py` — `stamp()` draws with reportlab in *displayed* coordinates (after /Rotate) and merges onto a page; `place_page()` draws one page scaled into a rectangle of another (n-up, resize, normalize). Font picking (`font_for`) falls back to a Unicode TTF for non-Latin text.
- `outlines.py` — read/remap/write bookmarks across documents.
- `imaging.py` — image → PDF pages (Pillow + reportlab).

### 6.1 Editor contracts and limitations

The editor keeps overlay coordinates in displayed PDF points with a top-left origin. Before submission it converts them to bottom-left displayed coordinates. The server transforms displayed coordinates into the original page's user space, accounting for page rotation and crop offsets. Do not mix this with raw unrotated MediaBox coordinates.

Page structure is applied first. `pageOrder` entries reference original 1-based pages and extra clockwise rotation, e.g. `"3:0"`, `"1:90"`, or a blank page `"-1:0:595x842"`. Drawing operation page numbers then refer to positions in that final order. Repeated pages are copied independently; duplicated copies do not retain their original annotations. The precise accepted schema is documented at the top of `app/tools/editor.py`.

| Editor payload field | Meaning |
|---|---|
| `appendTextOperations` | Add text with font, position, color and style |
| `editTextOperations` | Cover an existing text area and draw replacement text |
| `shapeOperations` | Rectangle/ellipse/whiteout overlays |
| `highlightTextOperations` | Highlight, strike-through or underline boxes |
| `imageOperations` | Image/signature data URL or stored image ID, size, placement and opacity |
| `appendDraw` | Freehand ink strokes |
| `appendLine` | Lines/arrows |
| `appendLinkOperations` | URI or page-link annotations |
| `appendFormFieldOperations` | New text/checkbox/dropdown/listbox/radio fields and their options |
| `formValues` | Fill existing named fields; multiselect values may be arrays |
| `flattenForms` | Flatten form/annotation appearances at the end of saving |

Find/replace works on horizontal PDF.js text runs, including adjacent fragments. It is not a general-purpose layout engine or secure redaction. Font matching is approximate; document-specific embedded-font editing and arbitrary transformed/vertical text replacement are not implemented.

### 6.2 Browser state

| Storage | Data/purpose | Lifetime/behavior |
|---|---|---|
| localStorage | `theme`, recent results | Theme persists; recent links are filtered by the client-side result lifetime |
| localStorage | `signatures` | Up to four remembered signature images; remain until removed/site data is cleared |
| localStorage | `editorDraft:v2:<document hash>` | Pages, overlays and form values; recovery window 48 hours, expired/corrupt drafts pruned when editor opens |
| localStorage | `workflows` | Saved reusable chains; passwords/credentials are scrubbed |
| sessionStorage | `lastStep`, `workflowChain` | Successful task recording and in-progress chain assembly |
| sessionStorage | `continueFiles` | Handover of output upload IDs to the next tool page |
| In-memory JS only | Workflow encryption passwords | Requested again per run and used for intermediate unlocking; not persisted/exported |

Browser storage is local to that browser/profile/origin; there is no account synchronization. Clearing site data removes these conveniences. Drafts can contain sensitive text, images and form values even after server files expire. Storage failure/full-storage cases should not prevent ordinary document processing.

### 6.3 Frontend

- `templates/base.html` — header (logo, "All tools" mega menu, theme toggle), footer, SVG icon sprite (`_icons.html`).
- `templates/index.html` — hero, search, category chips, tool cards (filtering is client-side).
- `templates/tool.html` — generic tool page: drop zone (device / URL), file list, page thumbnails (`#pages-ui`), options (basic + "More options"), submit, result panel, recent results, how-to, FAQ, related tools.
- `static/js/site.js` — `window.UI`: theme, mega menu, toasts, modal dialogs, helpers.
- `static/js/tool.js` — `window.Tool`: uploads (simple ≤5 MB, chunked >5 MB, 3 parallel chunks, link import, password prompt), file reorder/rotate (merge), `show_if` conditional options, form → JSON, submit, 402 countdown, polling every 3 s, result screen (download, preview, ZIP items, continue in another tool, delete now), recent results in localStorage, keep-alive `touch` every 10 min, files handed over via sessionStorage `continueFiles`.
- `static/js/pages-ui.js` — PDF.js thumbnails, selectors, rotations, organization, split marks, area/crop drawing, metadata and bookmark prefill.
- `static/js/editor.js` + `static/css/editor.css` — document editor, form overlays, signatures, text search/replacement, drafts and mobile touch interaction.
- `static/js/workflows.js` — saved-chain management, import/export, credential prompts and step execution.
- `static/js/home.js` / `theme.js` — home search/filtering and early theme application.
- `static/js/pdf-loader.js` + `static/vendor/pdfjs/` — ES-module preview renderer, worker, fonts, CMaps and codecs; no CDN script is required.
- `static/css/app.css` — design tokens (light/dark), all components.

## 7. Configuration

This section also covers setup, deployment, security, verification and maintenance. Settings are evaluated when application modules are imported; restart the server after changing them.

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

The built-in `.env` reader accepts simple assignments, comments and surrounding quotes; it does not provide shell expansion or variable interpolation. Use `ALLOW_PRIVATE_URLS=1`/`TRUST_PROXY=1` only deliberately: their boolean flags are enabled by the literal value `1`. Any non-empty `NO_DOTENV` value skips loading `.env`. Invalid integer settings fall back to code defaults; choose sensible positive limits.

Additional fixed limits: the browser uses 5 MB upload chunks with up to three parallel chunks; the backend permits chunks up to 10 MB. Upload request-body caps allow multipart overhead. The generic tool limit is 50 input files unless a registration overrides it; editor tools allow one PDF. These are not all environment settings.

### 7.1 Run locally

For a fresh checkout:

```powershell
git clone https://github.com/prarit0097/pdfsejeda.git
Set-Location pdfsejeda
```

For the existing workspace instead:

```powershell
Set-Location 'E:\coding\Sejda copy'
```

Create/install a Python environment and start the app:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m playwright install chromium

# Create the settings file only if it does not already exist.
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
# Edit .env and replace its SECRET_KEY placeholder with a long random value.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Stop the foreground server with Ctrl+C. Add `--reload` for development; reloading invalidates in-memory task records. Running locally serves your own computer; hosting it elsewhere makes that server the processor/storage location.

`requirements-lock.txt` installs the exact tested dependency snapshot, including Playwright and test dependencies. For compatible version ranges instead, install `requirements.txt`; add Playwright separately or install `requirements-test.txt`. A Python package install does not install LibreOffice, Tesseract or Chromium automatically. The browser-install command above installs Chromium for the current environment/user.

On macOS/Linux, create the environment with `python3 -m venv .venv` and use `.venv/bin/python` for the remaining Python commands. Windows x64/Python 3.13 was clean-install tested; the Docker recipe uses Python 3.12, and the Hostinger image was verified on Linux with Python 3.12.15 on 2026-10-22.

Generate a secret locally with `python -c "import secrets; print(secrets.token_hex(32))"`, put it in `.env`, and do not commit or share its value. No private `.env` contents belong in this document.

### 7.2 External engines and fonts

| Capability | What must be installed | Behavior when unavailable |
|---|---|---|
| DOC/ODT/RTF and faithful DOCX conversion | LibreOffice (`soffice`/`libreoffice`; common Windows/macOS paths are also checked) | DOCX/TXT use a basic converter with a warning; other supported Office formats need the engine |
| OCR | Tesseract and selected language packs | Task fails with an engine/language message; UI choices reflect detected packs |
| HTML printing | Python Playwright package and compatible Chromium browser | Missing package reports installation instructions; browser-launch failures may need server-log inspection |
| Browser PDF preview/editing | Included PDF.js modules/assets | No external preview CDN needed; a current browser is required |
| Unicode/complex-script output | Installed script-appropriate fonts; fonttools/uharfbuzz from requirements | Fallback/font coverage varies; missing glyph coverage can produce poor output |
| Optional interface/signature web fonts | Access to Google Fonts | System/default fonts remain usable; cosmetic font appearance can differ |

Inspect the actual runtime environment when diagnosing a missing engine. The UI listing a tool does not prove its optional system dependency is installed. A local user install and a Docker container have separate browser/font/engine paths.

### 7.3 Docker and hosting

```powershell
# Run from the repo root after preparing .env.
docker compose up --build
```

Compose exposes port 8000 and persists `/data` in the `pdfnova-data` named volume. The image installs locked Python dependencies, LibreOffice Writer, Tesseract with eng/hin/spa/fra/deu, fonts and Chromium, then runs as the unprivileged `pdfnova` user. `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` makes the installed browser accessible to that user. The health check requests `/api/tools`.

The build context excludes `.env`, `.venv`, `data`, QA directories, research and tests. Changing source requires rebuilding/restarting the container. Stopping a container does not remove its named data volume; do not delete that volume as a routine fix. **The image was built and run successfully on the Hostinger Linux server on 2026-10-22; container pytest passed 170 tests and live HTTP smoke passed 58/58.**

Deploy with **one Uvicorn process** until the queue, quota and task registry are moved into shared services. Put public deployments behind HTTPS and a trusted proxy; forwarded-header configuration must match the real proxy chain. Set a stable `SECRET_KEY`, keep private-URL access disabled and monitor storage/worker use. Do not assume the current local test results establish production capacity or security for every hosting setup.

**Shared Hostinger server deployment:** Live at https://pdf.praritsidana.com on `187.127.132.106`, in `/opt/pdfnova`. Dedicated Compose project/container `pdfnova` / `pdfnova-web-1`, volume `pdfnova_pdfnova-data`, and loopback-only backend `127.0.0.1:8086` keep it separate from other apps. The host Nginx site is `/etc/nginx/sites-available/pdfnova`; its exact configuration is committed as `deploy/hostinger/nginx.pdfnova.conf`. Let's Encrypt issuance, renewal dry-run, automatic renewal timer and domain-specific reload hook are verified. Production uses two processing threads, queue size eight, 1.5 CPUs, 2 GiB RAM, 256 PIDs, a nonroot user and child-process init. Quota is 20 tasks/IP/hour, uploads 100 MiB, retention two hours and private URL imports disabled. Nginx overwrites client-IP/protocol headers and clears `CF-Connecting-IP`; only this loopback-bound profile trusts forwarded headers. Keep the actual `.env.hostinger` private (mode 600, ignored by Git/build). Build options include `PDFNOVA_DEBIAN_MIRROR`, `PDFNOVA_PYTHON_PACKAGE_INDEX` and `PDFNOVA_PYTHON_OFFLINE`; the deployed image used 54 offline wheels checked against committed official PyPI SHA-256 hashes after CDN failures. See `deploy/hostinger/DEPLOYED.md` and `verification.json` for the image identity, evidence, operations and restart limitations. All 15 existing containers and 19 virtual-host responses matched the predeployment baseline.

### 7.4 Security, retention and concurrency details

- **Access model:** file/task IDs are bearer capabilities; there is no logged-in owner check. Task IDs contain 32 random characters from a 32-character alphabet (160 random bits), plus a UTC timestamp. Task polling can issue a signed download link to anyone who knows that task ID. Downloads check a per-task HMAC signature, but signatures are not an independent owner check. Never claim a signed result is accessible only to its original uploader.
- **Upload validation:** size/body caps apply while receiving data. A file may upload before its content is parsed; allowed extension/MIME checks happen at tool submission, and PDF/image/Office parsers perform format validation. Arbitrary upload storage is not the same as permitted tool input or executable content.
- **Safe serving:** unsafe names are sanitized, IDs are validated, and uploaded HTML/SVG/JavaScript are not rendered as active same-origin content. API responses use no-store; HTML pages have CSP, framing and content-type protections. Scripts/workers come from this app; optional Google Fonts are allowed. JavaScript eval is blocked while PDF.js WASM codec compilation is allowed.
- **URL/HTML fetching:** public-address validation and actual IP pinning cover redirects/resources. HTTPX ignores environment proxies. WebSockets/service workers cannot open an unrestricted network path. Ad/banner filtering is deliberately heuristic.
- **Expiry:** upload TTL slides on keep-alive; result TTL starts at task completion. Task lookup enforces expiry, and the sweeper physically removes expired disk data. Browser drafts/signatures/workflows have their own lifetimes and can outlive server files.
- **Processing:** default four workers and 32 waiting jobs bound admission before file IO; validation failures release capacity and overload refunds the hourly quota. Timeouts/cancellation are cooperative; native hangs cannot be forcibly terminated by this thread queue. A stuck PDFium operation can retain its lock and worker. There is no aggregate disk quota or process-level isolation per task yet.
- **PDFium:** all native document operations must remain within the shared `pdfium_doc()` lock scope. Do not retain live page/text/bitmap handles outside it or introduce direct unguarded native calls. Other independent PDF engines can still run concurrently.

### 7.5 Tests and verification status

Use generated non-confidential fixtures. Inspect output contents, page counts, fields or rendering as appropriate; an HTTP 200, a valid ZIP header or an unchanged snapshot alone is not enough for every operation.

```powershell
# Unit, handler and API tests; do not read the developer's .env.
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check

# These need a running server with suitable queue/quota settings.
.\.venv\Scripts\python.exe scripts/smoke_test.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/browser_regression.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/concurrency_regression.py http://127.0.0.1:8000

# Starts its own temporary server/data directory.
.\.venv\Scripts\python.exe scripts/editor_regression.py
```

The concurrency script submits 16 tasks, so disable/increase the hourly quota for that isolated test environment. Do not weaken public deployment settings merely to make a test pass. Browser tests require Playwright/Chromium. OCR/Office tests can depend on installed engines; report skips and fallbacks rather than treating them as proof of full engine coverage.

Last recorded full verification, **2026-10-22**:

| Verification | Recorded result |
|---|---|
| Clean Windows/Python 3.13 pytest | 170 passed, 0 failed; 2 deprecation warnings |
| Live HTTP smoke | 58/58 passed, including real LibreOffice, Tesseract and Chromium |
| Generic Chromium UI | 62/62 passed, including all 43 tool pages and real downloads |
| Editor/forms/workflows/mobile Chromium | 8 scenario groups passed |
| Concurrent HTTP jobs | 16/16 passed with downloaded output checks |
| Dependency consistency / asset hashes | `pip check` passed; 201 vendored PDF.js asset hashes verified |
| Docker/Linux build | Python 3.12.15 image built; 170 pytest passed (3 warnings), HTTP smoke 58/58; pip check passed |
| Hostinger HTTPS/browser/restart | Public UI 62/62, mobile editor saved a real PDF, spoofed proxy headers could not reset quota, restart/download checks passed |
| Hostinger native concurrency/isolation | 8/8 simultaneous PDF jobs, 2/2 HTML jobs; existing containers 15/15 and virtual hosts 19/19 unchanged |

Evidence: `research/audit-2026-10-22/verification.json`, `REPORT.md`, compact REA summaries and reproducible scripts. Raw evidence and QA screenshots remain local/ignored. These results are a historical baseline; update this table and evidence when behavior changes and fresh verification is run. Do not increase counts by counting assertions, aliases or screenshots as additional independent tests.

### 7.6 Contributor workflow and definition of done

1. Read this guide, `plan.md`, relevant research and the affected code/tests. Inspect the branch, remote and working tree first.
2. Establish the behavior being changed and a concrete success condition. Check whether it is implemented, incomplete, unverified or explicitly deferred.
3. Add/fix the smallest coherent implementation while preserving existing work. A new tool normally needs a handler, a `Tool(...)` registration with options, an import through registry loading, and UI support only where the generic template is insufficient.
4. For PDF/editor changes, preserve page orientation/crop coordinate contracts, form appearances, bookmark mappings, safe filenames and cancellation points. Keep PDFium calls guarded.
5. Add a meaningful regression for substantive behavior; validate real files and browser behavior where necessary. Do not add tests that only repeat implementation details. Run appropriate checks and ensure the pytest requirement in §1 is satisfied before pushing.
6. Update the behavior description here, add a dated §8 entry, update relevant `plan.md` items, and revise README/API/privacy guidance when the change affects them. Record actual checks and material limitations.
7. Inspect the diff, stage intentional files only, commit and push to `origin main`. Check for remote changes; resolve conflicts without discarding work or force-pushing. Keep secrets/data/raw captures out of the commit.

Useful inspection commands:

```powershell
git status --short
git remote -v
git branch --show-current
git diff --check
git diff --stat
git log -5 --oneline
```

The repository is the source of version history; use `git log`/`git show` for precise commits. `plan.md` tracks intended work, this file explains current behavior, and tests/evidence establish what was verified. When these disagree, inspect the implementation and evidence, repair the documentation, and do not silently treat an old plan checkbox as proof.

### 7.7 Known limitations and remaining work

- Exact UI/visual parity, every advanced option, all marketing/tutorial pages and every document-conversion edge case remain incomplete or unverified. Original branding/copy are retained under §1.
- Word/Excel extraction reconstructs layout heuristically. PPT output uses rendered page images and text notes; slide elements are not a fully editable reconstruction. Scans generally need OCR before text-oriented conversion.
- Visual text replacement/whiteout is not redaction; original text can remain extractable. Embedded-font preservation and arbitrary transformed/vertical text editing are not implemented.
- Advanced gaps include font subsetting, a full interactive bookmark-tree editor, arbitrary watermark positioning and evidence-backed per-source repeat semantics.
- Translated routes/copy, a native desktop installer and browser extensions are not implemented. Running the web app locally is different from shipping a desktop application.
- Multi-process/shared durable jobs/storage, aggregate disk quotas, hard termination of native hangs, and sustained production load testing remain work for a later phase. The single-server Docker/Linux deployment is verified within the recorded scenarios and resource limits.
- HTML printing does not provide US/EU hosted-browser selection or automatic orientation. Authenticated sessions, complex redirected module scripts and some external-site rendering can differ from a normal browser.
- Accounts/billing, cloud integrations and email signing are **deliberately deferred by the user**, not current blockers. Do not reintroduce them through a roadmap item or fake working UI.

For the detailed audit and remaining evidence boundaries, read `research/audit-2026-10-22/REPORT.md`.

### 7.8 Troubleshooting

| Symptom | Check/action |
|---|---|
| `ModuleNotFoundError` | Use the intended `.venv` interpreter and install requirements into that environment |
| Port 8000 is occupied | Identify the process first; stop only an owned server or choose another port |
| Settings appear unchanged | Environment variables override `.env`; restart after changing settings; check whether `NO_DOTENV` is set |
| DOCX conversion loses layout | Look for the explicit basic-converter warning; install/fix LibreOffice and suitable fonts |
| LibreOffice fails on Windows | Verify detected launcher and isolated short profile path; do not remove the profile-isolation fix |
| OCR missing/wrong language | Check Tesseract detection, installed language packs and `TESSDATA_PREFIX` if used by that engine |
| HTML converter cannot launch browser | Install Playwright and its Chromium in the running environment/user; container paths differ from host paths |
| URL import is rejected | Use a direct public HTTP(S) file address; local/private addresses are intentionally blocked by default |
| Result is expired after reload/restart | In-memory tasks are lost on server restart; upload the original and rerun; do not promise persistent task links |
| HTTP 402 | Enabled hourly task quota exhausted; use the returned wait time |
| HTTP 429 | Job admission is full; retry later and inspect long-running work rather than creating unlimited threads |
| HTTP 413 | File/chunk/request exceeds its configured limit |
| Preview works but save fails | Check the task's failure reason/server log; editor drafts should remain available until a successful save |
| Text appears as boxes or joins incorrectly | Install fonts covering that script and the shaping dependencies; compare actual saved/rendered output |
| Output text is still extractable after whiteout | Expected limitation of visual overlays; use a dedicated redaction tool for permanent removal |
| Cleanup cannot remove a file on Windows | Check open native handles; explicitly close them and allow the next sweep, without deleting unrelated data |

Logs go to server stdout/stderr. Known task failures expose a safe message; unexpected errors are logged and return a generic processing message. Avoid posting logs containing file/task IDs, URLs with credentials, document contents or passwords.

### 7.9 Research, provenance and keeping this guide complete

- `research/SEJDA.md` is the consolidated behavioral report. `research/SEJDA-REVERSE-ENGINEERING.md` is the initial investigation; agent runtime/static/desktop notes and `live-verification.md` contain more specific evidence.
- `research/sejda-tools-catalog.json` records observed controls/task types. A control name does not establish its server semantics or prove this app implements it.
- REA was used for public/runtime observation. The 2026-10-22 pass used installed REA 6.7.0 CLI because MCP tools were unavailable; no client registration change or native decompiler installation was needed. Public Sejda page observation and local processing scenarios are distinguished in the audit.
- Full raw browser records can contain ephemeral tokens and are kept local via `.gitignore`; compact evidence IDs, inputs, summaries and findings are committed. Do not relabel ordinary browser/shell observations as REA output.
- `app/static/vendor/pdfjs/manifest.json` records the pinned official package, archive hash and selected asset hashes. Retain upstream license/codec/font notices and preserve vendored bytes when upgrading. No Sejda shipped application JavaScript belongs in the app.
- Keep this guide self-contained for normal use: product identity/purpose, scope, architecture, all tools/routes, setup/configuration, data/access model, tests, contributor rules, limitations and recent changes should remain here. Link supporting evidence instead of copying confidential captures or every implementation line.

## 8. Change log

Newest first. One line per change: date — what — where.

- 2026-10-22: Deployed PDFNova to https://pdf.praritsidana.com in isolated `/opt/pdfnova`. Linux pytest 170, HTTP 58/58, private/public generic browser 62/62 each, editor 8 groups, public mobile save, PDF concurrency 8/8, HTML concurrency 2/2, quota/header isolation, TLS renewal and restart recovery passed. Existing 15 containers and 19 virtual hosts unchanged. Deployment evidence and maintenance instructions recorded in `deploy/hostinger/DEPLOYED.md` and `verification.json`.





- 2026-10-22 — Expanded this file into the complete project guide: product identity/purpose, scope, stack rationale, full layout/API reference, editor/storage contracts, setup/engines/Docker, security/retention, dated verification, contributor workflow, limitations and troubleshooting. Documentation checks covered all 43 registered tools, 13 environment settings and 17 API routes; links/fences passed, and pytest remained 170 passed with 2 deprecation warnings — `sejedarules.md`

- 2026-10-22 — User deferred accounts/billing, cloud integrations and email signing from the current delivery scope; ordinary local PDF signatures remain included — `plan.md`, `sejedarules.md`, audit report

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
