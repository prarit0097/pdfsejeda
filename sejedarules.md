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

Format: `type` — `/page-slug` — key options — how it works. Every tool lives in `app/tools/<group>.py` and registers itself with `register(Tool(...))`; the tool page renders its options form from that registration.

**Organize** (`app/tools/organize.py`)
- `merge` — `/merge-pdf` — `outlinePolicy` (retain/discard/one_entry_each_doc/retain_as_one_entry), `tocPolicy` (none/file_names/doc_titles), `acroFormPolicy` (merge/merge_renaming/flatten/none), `blankPageIfOdd`, `normalizePageSizes`, `filenameFooter`, `outputFilename`, `rotations[]` per file. Images become A4 pages first. TOC pages get clickable links.
- `splitByPages` — `/split-pdf` — `splitMode` every/after/even/odd, `step`, `pages` (split *after* these), `specificResultFilenames[]`, `outputFilenamePattern` tokens `[BASENAME] [CURRENTPAGE] [FILENUMBER] [TIMESTAMP]`, `discardOutline`.
- `splitByBookmarks` — `/split-pdf-by-outline` — `bookmarksLevel` 1–3, `bookmarksExpression` (regex filter), `includePageAfter`. Files are named after the bookmark.
- `splitBySize` — `/split-pdf-by-size` — `size` + `sizeUnit` MB/KB. Greedy: grows each chunk while the real saved size fits.
- `splitByText` — `/split-pdf-by-text` — `area {x,y,width,height}` (PDF points, **top-left origin**, drawn on page 1 in the UI), `startsWith`. New file whenever the text in the area changes; files are named after the text.
- `splitDownTheMiddle` — `/split-pdf-down-the-middle` — `mode` auto/vertical/horizontal, `ratio`, `excludedPages`, `autoDetectExcludedPages`, `rightToLeft`, `repagination` (booklet order). Works by duplicating each page and setting two CropBoxes.
- `alternateMix` — `/alternate-mix-pdf` — `reverse` (second file reversed), `step`. ≥2 files.
- `extractPages` — `/extract-pdf-pages` — `pages`, `discardOutline`.
- `deletePages` — `/delete-pdf-pages` — `pages`, `discardOutline`. Refuses to delete every page.
- `combineReorder` — `/organize-pdf` — `filePages ["fileIdx:page:rot"]` in final order, `"-1:-1:rot"` = blank page, `outputFilename`. Without `filePages`: all pages of all files.
- `rotatePages` — `/rotate-pdf-pages` — `pageRotationsPerSource ["fileIdx:page:deg"]` (per page, wins) or `rotation` + `pages` (bulk). Rotation is added to the existing /Rotate.

**Optimize & layout** (`app/tools/modify.py`)
- `compress` — `/compress-pdf` — `imageQuality` 0.65/0.8/1 (JPEG q 55/72/90), `imageDpi` (downsample above it, estimated from page size), `imageConversion` grayscale, `discardMultimedia`. Re-encodes each image only if smaller, drops unused resources, saves with object streams. Never returns a bigger file (unless `failIfOutputSizeNotReduced`).
- `crop` — `/crop-pdf` — `cropMode` auto (render with PDFium, find non-white bbox, union over pages if `sameForAllPages`) / margins (`unit` + 4 margins) / area (drawn on page 1). Sets CropBox and MediaBox.
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
- `docToPdf` — `/word-to-pdf` — LibreOffice headless when installed (isolated profile per task); otherwise a basic built-in DOCX/TXT renderer with a warning.
- `htmlToPdf` — `/html-to-pdf` — Playwright Chromium; `urls` (one per line), `htmlCode`, uploaded .html files; `pageSize`, `pageOrientation`, `viewportWidth`, `pageMargin`+units, `delay`, `usePrintMedia`. Every request the browser makes is checked against private addresses.
- `ocr` — `/ocr-pdf` — Tesseract renders each page at 300 dpi and makes a text-only PDF layer (`textonly_pdf=1`) that is overlaid invisibly on the original page; `lang`, `outputFormats` pdf/txt.

**Optional system tools** — detected at runtime by `find_binary()`: LibreOffice (`soffice`), Tesseract (`tesseract`), Playwright Chromium. Tools that need a missing one fail with a clear message instead of crashing.

**Shared building blocks** (`app/tools/`)
- `common.py` — open/save PDFs with passwords, page sizes, `output_name` (honours `outputFilenamePattern`).
- `draw.py` — `stamp()` draws with reportlab in *displayed* coordinates (after /Rotate) and merges onto a page; `place_page()` draws one page scaled into a rectangle of another (n-up, resize, normalize). Font picking (`font_for`) falls back to a Unicode TTF for non-Latin text.
- `outlines.py` — read/remap/write bookmarks across documents.
- `imaging.py` — image → PDF pages (Pillow + reportlab).

## 5a. Front end

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

## 8. Change log

Newest first. One line per change: date — what — where.

- 2026-10-22 — Phase 5: PDF→JPG/PNG/TIFF, JPG→PDF, extract images, PDF→text, PDF→Excel/CSV, PDF→Word, PDF→PowerPoint, Word→PDF (LibreOffice + fallback), HTML→PDF (Playwright), OCR (Tesseract text layer) — `app/tools/convert.py`, `tests/test_convert.py`
- 2026-10-22 — Phase 4: compress, crop, resize, n-up, flip, grayscale, deskew, flatten, repair, header/footer, page numbers, Bates, watermark, encrypt, unlock, metadata, bookmarks, delete annotations, rename by text; `/api/files/<id>/outline` and `/metadata`; 38 tests — `app/tools/modify.py`, `stamp.py`, `security_tools.py`
- 2026-10-22 — Phase 1–3: platform core (config, FileStore, JobQueue, page parser, HMAC links, SSRF-safe URL import, per-IP quota), full `/api` (upload, chunked upload, URL import, password, touch, view, tasks, change, download, cancel, delete, continue, tools), UI (design system, home, generic tool page, thumbnails), 11 organize tools, 21 tests — `app/`, `tests/`
- 2026-10-22 — Project started: plan.md and sejedarules.md written; Python/FastAPI stack chosen — `plan.md`, `sejedarules.md`
