# SEJDA.md: complete reverse-engineering findings for sejda.com

Everything found across all passes, in one file. Generated 2026-10-21 from the files in this folder; nothing was summarised away.

**Sources merged:**
| Pass | How | Source file |
|---|---|---|
| 1 | First pass: REA + static HTML/JS analysis, page crawl (robots.txt crawl-delay respected) | SEJDA-REVERSE-ENGINEERING.md |
| 2 | Agent 1: REA browser scenarios in headless Edge, 2 real tasks | agent-1-runtime.md |
| 3 | Agent 2: static deobfuscation, no target code executed | agent-2-static.md |
| 4 | Agent 3: Sejda Desktop 7.9.11 unpacked, never installed or run | agent-3-desktop.md |
| 5 | Live verification: 1 upload, 1 task, 1 over-quota request | live-verification.md |
| 6 | Tool catalog: every option of every page | sejda-tools-catalog.json |

**Confidence tags used throughout:**
- **[seen]** / **[observed]** = read directly in shipped code or live traffic.
- **[observed-js]** = read in code that ran but was not exercised.
- **[inferred]** = deduced, not verified.
- **[unknown]** = not determinable.

When parts disagree, the **later** part wins (Part 5 > 4 > 3 > 2 > 1). Part 1 already carries the merged corrections, marked **(corrected)**.

**Out of scope on purpose:** cracking or forging download signatures, provoking 429/430 by flooding, bypassing captcha, paywall or licensing, and reproducing hard-coded keys or tokens. Their existence is documented; their values are not.

## Table of contents
1. Part 1: Main report (first pass + merged updates)
2. Part 2: Agent 1, runtime capture in a real browser
3. Part 3: Agent 2, static deobfuscation and payload schemas
4. Part 4: Agent 3, Sejda Desktop teardown (the engine)
5. Part 5: Live verification of the remaining unknowns
6. Part 6: Full tool catalog (every option of every page)

---

# Part 1: Main report (first pass + merged updates)

> The base analysis, updated with corrections from every later pass. (source: `SEJDA-REVERSE-ENGINEERING.md`)

Analysed on 2026-10-21 using REA plus static analysis of the public HTML/JS. Nothing was executed against Sejda's servers beyond normal page/script downloads (robots.txt crawl-delay respected; `/api/` was never called).

Machine-readable catalog of every tool and its form options: [sejda-tools-catalog.json](sejda-tools-catalog.json)

**Second pass (3 parallel REA agents), with full detail in:**
- [agent-1-runtime.md](agent-1-runtime.md): live browser capture of 2 real tasks (compress, edit). Covers the results page, polling, download URLs and real payloads.
- [agent-2-static.md](agent-2-static.md): the editor fully deobfuscated. Covers JSON schemas for all editor operations, task serialization, page-selection encoding, workflows, login and storage.
- [agent-3-desktop.md](agent-3-desktop.md): Sejda Desktop 7.9.11 taken apart. Covers the Java engine stack, the task-type → engine-class map, and which features are server-only.

Sections below are updated with their findings. Anything the second pass corrected is marked **(corrected)**.

**Confidence key:** **[seen]** = read directly in shipped HTML/JS. **[inferred]** = deduced from names or strings and not verified. **[unknown]** = not visible from the client side.

---

### 1. Architecture in one picture

```
Browser (jQuery app, server-rendered HTML per tool)
  │ 1. POST /api/files/upload-check                     (pre-flight, cookie session)
  │ 2. POST /api/files/upload?uplid=…   (≤5 MB, multipart)
  │    POST /api/files/upload-chunked   (>5 MB, 5 MB chunks, up to 4 parallel)
  │       → returns file id → hidden <input name="files[]">
  │ 3. POST /api/tasks   JSON {type:"compress", files:[…], …options}
  │       → 200: taskId → URL hash #results… → iframe "result?id=<taskId>"
  │       → 402 paywall | 429 slow down | 430 captcha required
  │ 4. Result iframe → download / Google Drive / Dropbox / OneDrive
  │    DELETE /api/tasks/<id>   POST /api/tasks/<id>/cancel
  ▼
Servers do ALL PDF processing (Sejda Web). Sejda Desktop does the same locally.
```

All PDF processing happens on the server. The browser only uploads files, collects options, previews (PDF.js) and downloads. The PDF editor is the one exception: rendering and editing happen in the browser, but the final save is still a server task (`type: "edit"`).

### 2. Front-end stack [seen]

| Piece | Evidence |
|---|---|
| jQuery 3.5.1 + jQuery Migrate 3.0.1 + jQuery UI 1.12.1 | banners in `libs-and-partials.min.js` |
| Bootstrap 3 (modals, tooltips) | `.modal`, `bs.modal` events |
| jQuery File Upload (blueimp) | `chunksend`, `chunkdone`, `maxChunkSize`, `maxConcurrentChunks` |
| PDF.js (self-hosted) | `/cache/149/js/pdfjs/pdf.worker.min.js`, `cMapUrl:/js/pdfjs/web/cmaps/`, `standardFontDataUrl:/js/pdfjs/web/standard_fonts/` |
| signature_pad (szimek) | signature drawing |
| zip.js (`/js/zip-no-worker-deflate.min.js`) | used before upload (see §4) |
| Sentry browser 5.27.4 (as `Raven`) | error reporting |
| mailcheck 1.1.2, jquery.serializeJSON, lodash/underscore `_` | banners/usages |
| Google Picker + Drive (`drive.file`, `drive.install` scopes), Dropbox Chooser, OneDrive v7.2 | cloud import/export |
| Google Identity Services (`accounts.google.com/gsi/client`) | Google login |
| FastSpring + Stripe + PayPal | checkout (`Sejda.FastSpring.popupWebhookReceived`, `stripePublicKey`, `paypalEnv`) |
| Self-hosted analytics `a.sejda.com/js/pa-….js` | page analytics |

**Page structure [seen]:** one server-rendered HTML page per tool. Two bundles cover everything: `libs-and-partials.min.js` (~800 KB, shared by all pages) and a per-page script. The editor's page script is obfuscated (`pdf-editor.min.obfuscated.js`, javascript-obfuscator with a base64 string array; I decoded its 2,070 strings statically). Pages are translated into 30+ languages under `/<lang>/…`.

### 3. Tool page anatomy [seen]

Every tool page contains:

- `#task-content` with `data-task="<type>"` (and `data-workflow` for workflow runs).
- An upload form `#fileUploadForm` with `action=/api/files/upload?_s=&uplid=<random>`, `data-filetypes`, `data-chunked-uploads`, `data-parallel-chunked-uploads`, `data-max-file-size="500"` and `data-free-limit-file-size`.
- `form.task-form` holding a hidden `type`, the tool's options, and `files[]` hidden inputs that are added as uploads finish.
- Per-file password prompts (`filePwd`, `usePwdForAllFiles`). **(corrected)** Passwords are not part of the task JSON. They are saved separately with `POST /api/files/<id>/password`.
- "More options" toggles, a recent-files list (IndexedDB, `source:"sejda_task_result"`) and a support/contact form. The support form can attach console logs, a screenshot, OS info and `allowAccessLastTask`.
- A hidden field `suflet=iluzie` [seen]. It has a constant value, so it is probably a bot/honeypot marker [inferred].

### 4. Upload pipeline [seen]

1. **`uplid`:** a random upload-session id is rendered into the page and sent with every upload.
2. **Pre-check:** `POST /api/files/upload-check` with `{uplid}` and `withCredentials`. Uploads are serialised, and a second submission within 10 s is cancelled.
3. **Optional zip wrap:** if the file is a PDF under 20 MB, the browser is not mobile, and `zipEnabled` is not turned off, the client zips it with zip.js at `level:0` (no compression) using a fixed password hard-coded in the JS, then uploads the zip. This probably keeps network middleboxes and antivirus proxies from inspecting or blocking PDFs [inferred]. A clone doesn't need this.
4. **Upload size:**
   - **≤ 5 MB:** one multipart POST to `/api/files/upload`.
   - **> 5 MB:** `/api/files/upload-chunked` in 5 MB chunks with `Content-Range`, up to 4 chunks in parallel.
   - Every upload sends the header `X-FileLocalId: <localId>`.
5. **Images:** images are converted client-side first (`Sejda.Images.convertImages`).
6. **Done:** the `fileUploadDone` event fires and a hidden `files[]` input with the server file id is added to the task form.
7. **Keep-alive:** `POST /api/files/<id>/touch` keeps uploaded files from expiring. A 404 response shows the "upload again" modal. After a 429, touching pauses for 1 hour.
8. **Import from a link (corrected):** Google Drive, Dropbox, OneDrive and plain URLs all become link files. The import itself is `POST /api/files {"url":…}`, which returns `{"id":"<uuid>-<16 chars>_2"}`. For preview, the browser first fetches the PDF directly. If CORS blocks that, it falls back to `GET /api/files/client-view?url=` with an `x-proxy-token` header taken from `<body data-proxy-token>`. Same-host (sejda.com) URLs are rejected client-side.
9. **Retention (claimed on pages):** "Automatically deleted after 2 hours".

### 5. Task execution [seen]

```js
$.jsonPost("/api/tasks", formJSON)   // {type, files:[…], filePwd…, outputFilenamePattern, …options, captchaToken?}
```

**Responses:**

| Status | Meaning | Client behaviour |
|---|---|---|
| `200` | task id | sets `location.hash`, opens an iframe at `result?id=<id>[&partnerKey&returnEmail]` |
| `402` | paywall | reason e.g. `tasks-per-hour`; reads the `X-RateLimit-Wait` header and starts a countdown clock |
| `430` | captcha required | shows the captcha modal, then resubmits with `captchaToken` |
| `429` | rate limited | "Too many attempts" |
| `400` | validation error | the response text is shown to the user |

On success the client also reads the `X-RateLimit-Remaining` and `X-RateLimit-Wait` headers and fires `quota-updates`.

**Results and cleanup:** closing the results modal calls `POST /api/tasks/<id>/cancel` if the task hasn't completed. Deleting from recent files calls `DELETE /api/tasks/<id>`.

**Request body (observed live):** `/api/tasks` is serialised with `serializeJSON({parseAll:true})`, so `pages:"5"` arrives as the number `5`.
- `files` is a flat array of file-id strings.
- Every body also carries telemetry: `uri`, `userAgent`, `cvts`, `pdfjs`, `libsCache`, recent `consoleLogs`, `traceId`, and `www` (the backend node).
- The response is the task id as a JSON string, e.g. `"YHLFMUJQ-202610211908"`, plus `x-ratelimit-remaining` and `x-ratelimit-wait` headers.

**Results page (observed live):**
- The iframe `result?id=<id>` loads `/js/pages/result.min.js` and polls `GET /api/tasks/<id>/change`.
- While the status is queued or processing it polls every 3 s. On errors it retries after 10 s, and a 404 means "expired".
- The completed response contains `status`, `type`, `remark`, `resultFilename`, `resultFileSize`, `resultFullUrlPattern`, `warnings`, `resultItems` and `id`.
- **Download:** `resultFullUrlPattern` with `{{filename}}` filled in, giving `/api/tasks/<id>/download/<file>?s=web-<sig>&d=true&_s=<node>`.
- **Preview:** uses `v=true&_xpt=<token>`.

**Cookies:** `clientId`, `_s`, `lang`, and an HttpOnly `JSESSIONID`.

**Other endpoints seen:** `/users/logout`, `/api/sign/email`, `/api/sign/link`, `/process/detect-form-fields`, `/api/files/<id>` (password save), `https://www.sejda.com/call/…`.

### 6. Every tool: task type and options [seen]

`mode` / `thumbsSize` are page-thumbnail UI options shared by many tools and are left out below. Full values are in the JSON catalog.

| Page | Task `type` | Input files | Options |
|---|---|---|---|
| alternate-mix-pdf | `alternateMix` | pdf (+images) | `reverse`, `step[]` |
| bates-numbering-pdf | `batesNumbering` | pdf | `pattern` (e.g. `Exhibit [FILE_NUMBER] - Case XYZ - [BATES_NUMBER]`), `batesDigits`, `batesStartFrom`, `batesIncrement`, `fileCountStartFrom`, `addMargins`, `font`, `color`, `style`, `pageLocation`, `fontSize` |
| compress-pdf | `compress` | pdf | `imageQuality` 0.65/0.8/1, `imageDpi` 72–720, `imageConversion` none/grayscale, `discardMultimedia`, `subsetFonts` |
| crop-pdf | `crop` | pdf | mode all/individual/odd-even, margins, `areaWidth/Height`, `unit` inch/cm, `autoCropMode` |
| delete-pdf-annotations | `deleteAnnotations` | pdf | `annotationTypes[]` (all, highlight, strikeout, underline, ink, polygon, square, circle, line, polyline, link, text, freetext, popup), `pages` |
| delete-pdf-pages | `deletePages` | pdf | `pages`, `discardOutline` |
| deskew-pdf | `deskew` | pdf | `angles`, `pages`, `onlyStronglySkewed` |
| edit-pdf-metadata | `editMetadata` | pdf | `removeAllMetadata`, `metadata.<Field>` |
| encrypt-pdf | `encrypt` | pdf | `userPassword`, `ownerPassword`, `encryptionAlgorithm` rc4_128/aes_128/aes_256, `permissions[]` (modify, copy, degradedprinting, print, fill, modifyannotations, assemble) |
| extract-images-from-pdf | `extractImages` | pdf | none |
| extract-pdf-pages | `extractPages` | pdf | `pages` (incl. odd/even), `discardOutline` |
| extract-text-from-pdf | `extractText` | pdf | none |
| flatten-pdf | `flatten` | pdf | `flattenMode` all/onlyforms, `resolution` 75–220 |
| flip-pdf | `flip` | pdf | `flipMode` horizontal/vertical |
| grayscale-pdf | `grayscale` | pdf | `textConversion` grayscale/black, `imageConversion`, `compressImages` |
| header-footer-pdf / page-numbers-pdf | `headerFooter` | pdf | `pattern` with tokens `[PAGE_ARABIC] [PAGE_ROMAN] [TOTAL_PAGES_ARABIC] [BASE_NAME]`, `font` times_roman/helvetica/courier, `color`, `fontSize` 6–28, `pageLocation` (6 positions), `pages`, `pageCountStartFrom`, `addMargins` |
| html-to-pdf | `htmlToPdf` | URL / html | `urls`, `pageSize` A4/A3/A2/Letter/Legal, `pageOrientation`, `pageMargin`+`pageMarginUnits`, `viewportWidth`, `delay` 0–5 s, `usePrintMedia`, `blockAds`, `hideNotices`, `partialContentAllowed`, `browserLocation` us/eu, `lang`, `timezone`, `includeHeaderFooterDetails` |
| jpg-to-pdf | `jpgToPdf` | png/gif/jpg/tif/bmp/webp | `pageSize` auto/custom/A5–A1/letter, `pageSizeWidth/Height`, `pageOrientation`, `pageMargin`, `mergeOutputs` |
| merge-pdf | `merge` | pdf + images | `outputFilename`, `blankPageIfOdd`, `normalizePageSizes`, `firstInputCoverTitle`, `filenameFooter`, `outlinePolicy` retain/discard/one_entry_each_doc/retain_as_one_entry, `tocPolicy` none/file_names/doc_titles, `acroFormPolicy` none/merge/merge_renaming/flatten |
| n-up-pdf | `nup` | pdf | `n` 2/4/8/16/32, `pageOrdering`, `preservePageSize`, `rightToLeft` |
| ocr-pdf | `ocr` | pdf | `outputFormats[]` pdf/txt, `lang` |
| organize-pdf | `combineReorder` | pdf | `outputFilename` (+ page order/rotation from thumbnails) |
| pdf-bookmarks | `editBookmarks` | pdf | `jsonData` (bookmark tree) |
| pdf-editor | `edit` | pdf | see §7 |
| pdf-forms | `edit` | pdf | form-field subset of the editor |
| sign-pdf | `fillSign` | pdf | editor subset + `emailTo/From/Requester` (request a signature by email) |
| pdf-to-excel | `pdfToExcelNext` | pdf | `exportFormat` excel/csv, `singleSheet` |
| pdf-to-jpg | `pdfToImage` | pdf | `pages`/`allPages`, `resolution` 75/150/220, `imageFormat` jpg/png/tiff, `tiffSingleFileWithAllPages`, `imageColorType` rgb/grayscale/black_white |
| pdf-to-ppt | `pdfToPpt` | pdf | none |
| pdf-to-word | `pdfToOfficeWord` | pdf | none |
| rename-pdf | `renameByText` | pdf | `areas` (JSON rects), `renamePattern` |
| repair-pdf | `repair` | pdf | none |
| resize-pdf | `resizePages` | pdf | `pageSize` a1–a6/letter/custom, width/height, margins, `unit` |
| rotate-pdf-pages | `rotatePages` | pdf | per-page rotation from thumbnails |
| split-pdf | `splitByPages` | pdf | `step` (every N), `pages`, `discardOutline`, `filename` |
| split-pdf-by-outline | `splitByBookmarks` | pdf | `bookmarksLevel` 1–3, `bookmarksExpression` (regex), `includePageAfter` |
| split-pdf-by-size | `splitBySize` | pdf | `size`, `sizeUnit` MB/KB |
| split-pdf-by-text | `splitByText` | pdf | `area[x,y,width,height]`, `startsWith` |
| split-pdf-down-the-middle | `splitDownTheMiddle` | pdf | `ratio`, `mode` auto, `autoDetectExcludedPages`, `excludedPages`, `repagination` last-first, `rightToLeft` |
| unlock-pdf | `decrypt` | pdf | file password only |
| watermark-pdf | `watermark` | pdf (+image) | `watermarkText`, `fontSize`, `color`, `opacity`, `pageLocation` centered/custom, `imageWidth/Height`, `pages`, `jsonData` (placement) |
| word-to-pdf | `docToPdf` | doc/docx | none |
| workflows | per step | pdf | `workflowId`, `automaticStart` (chains of the tasks above) |

**Non-tool pages:**

- **`/desktop`, `/upgrade`, `/html-pdf-api`:** checkout pages with seats, discount, VAT, billing country, Stripe/PayPal/FastSpring.
- **`/developers`:** documents the HTML-to-PDF API and Desktop license lookup.

### 7. PDF editor internals (`pdf-editor`, `pdf-forms`, `sign-pdf`) [seen, from decoded strings]

**Rendering:** PDF.js renders each page as layers: a canvas, a text layer (`renderTextTask`), an annotations layer (`renderAnnotationsTask`) and a form layer (`renderFormTask`). A `RenderingQueue` renders pages lazily, plus a `guidesLayer` for snapping.

**Tools:**

| Category | Tools |
|---|---|
| Text | text tool (add text); edit existing text inline (`editTextOperations`, `data-inline-editor-id`) |
| Annotations | highlight, freehand highlight, strikethrough, underline |
| Drawing and shapes | draw (freehand), shapes, line |
| Images | image, existing-image (move or delete images already in the PDF) |
| Links | link tool (`kind` uri/mailto/tel/page) |
| Form fields | form-field tool, auto-detect form fields (`/process/detect-form-fields`), tab ordering, publish form |
| Signatures and stamps | sign tool, signature (typed / drawn / camera photo / uploaded), stamps (`stampDateStyle` none/date/date-time…) |
| Other | whiteout, attachments (embedded files), undo, find & replace (`findText`, `replaceText`, match case, links) |
| Page tools | insert page (`new-page-template`), rotate, delete page |

**Font handling:**
- **Reuse:** the editor tries to reuse the document's own embedded font (`findDocFont`, `findDocFontByFontFace`).
- **Missing glyphs:** if the embedded font lacks characters you typed, it substitutes another font and warns "Original font replaced, was missing characters you typed" (`FontReplacementModal`).
- **Font types:** it handles `CIDFont` and `Type3` cases specially.
- **Extra fonts:** more can be loaded from `/css/pdf-editor/fonts.css`.

**Save format:** the editor collects operation lists and sends them as one `edit` task:
`editTextOperations, appendTextOperations, imageOperations, deleteImageOperations, shapeOperations, highlightTextOperations, editHighlightOperations, deleteHighlightOperations, appendLinkOperations, editLinkOperations, deleteLinkOperations, appendFormFieldOperations, deleteFormFieldOperations, appendAttachmentOperations, deleteAttachmentOperations, appendEmbeddedFileOperations, deleteEmbeddedFileOperations, insertPageOperations, rotatePageOperations`.
The server applies these operations to the original PDF. The browser never writes PDF bytes.

**Additional operation types (second pass):** `deletePageOperations`, `appendDraw` and `appendLine`, for 25 operation types in total. Every array is sent, even when empty.

**Coordinate system:** coordinates are CSS pixels divided by the page's display scale, which gives PDF points with the origin at the bottom-left of the displayed (rotated) page. `editTextOperations.area` is the one exception and uses top-left coordinates.

**Pages:** `pages` holds 1-based editor positions. `deletePageOperations` uses original page numbers instead.

**Real `appendTextOperations` item:**
```json
{"text":"…","font":"Helvetica","fontSize":"10.00","position":{"x":…,"y":…},"lineHeight":…,"color":"#000000","bold":false,"italic":false,"pages":"1"}
```

The full schemas for all 25 types are in [agent-2-static.md](agent-2-static.md).

**Other editor details:** the editor has a domain lock that sends the page to `about:blank` when it runs outside `.sejda.com`, and it loads 12 self-hosted handwriting fonts for signatures.

**Page-selection encoding (other tools):**
- **Ranges:** pages are sent as strings like `"1-3,7"`.
- **`rotatePages`:** `pageRotationsPerSource:["fileIdx:page:deg"]`.
- **`combineReorder` (organize):** `filePages:["fileIdx:page:rot"]`, with `"-1:-1:rot"` for an inserted blank page.

**Other editor behaviour:**
- **Crash recovery:** `EditorRecovery` autosaves unsaved edits in local storage and can restore them later (`recovered` flag).
- **Free tier:** "3 free saves", "No free saves left for the next …" (save quota per hour). "Potential scan" detection prompts the user to run OCR.
- **Remote signing:** `/api/sign/email` and `/api/sign/link` create signature requests sent by email or link.

### 8. Business rules / limits [seen in page text]

**Free tier:**
- 3 tasks per hour and 30 files per hour.
- Files up to 100 MB on most tools; HTML-to-PDF is limited to 30.
- 50 pages per conversion (20 on some converters).
- OCR up to 10 pages per task.
- Editor: 3 free saves per hour.

**Paid tiers:**
- **Plans:** Web Week Pass (one-time, 7 days, no auto-renew), Web annual/monthly, Desktop+Web annual, team seats with volume discount.
- **Limits:** files up to 500 MB, no hourly or page limits, OCR up to 100 pages.
- **Payment:** prices are loaded dynamically through FastSpring and Stripe [unknown amounts].

**Abuse controls:** a captcha after suspicious use (HTTP 430), rate-limit headers, and a 10-second upload throttle.

### 9. The engine, as seen in Sejda Desktop 7.9.11 [seen, from agent 3]

**Desktop app framework:** Electron 42.4.0 running the same jQuery front end as the website. ASAR integrity checking and OnlyLoadAppFromAsar are on; RunAsNode is off.

**How a task runs:** there is no local server.
1. The preload script writes the task JSON to `task.in`. It is the same format the web sends to `/api/tasks`.
2. A fresh bundled Java 25.0.3 process starts running `DesktopLauncher` (written in Scala).
3. The Java process writes the result to `task.out`.

Cancelling creates a `task.kill` file. The 10 IPC channels only handle dialogs, menus, fonts and paths.

**Engine stack:**

| Layer | Component |
|---|---|
| PDF core | **SAMBox 3.0.38**, Sejda's Apache-2.0 fork of PDFBox |
| Basic tasks | **Sejda SDK 5.1.23**, open source (AGPL-3.0) |
| Advanced tasks | Sejda "pro" modules 5.1.21 + `com.sejda.common` (13.7 MB), proprietary |
| Task registry | `sejda.xml` maps each parameters class to a task class (full table in agent-3) |
| PDF→Word / PDF→Excel | `pdf2html` 0.0.74 + Apache POI |
| OCR | Tesseract 4.0.0 (English bundled; other languages downloaded from sejda-cdn.com) |

**Server-only features:**
- **Missing tools:** the desktop app bundles no Ghostscript, LibreOffice, qpdf or HTML renderer.
- **Missing engines:** HTML→PDF, PDF→PPT and the "Office"-quality Word/Excel conversions have no engine registered in Desktop, so they run only on Sejda's servers.
- **Likely server stack** [inferred]: a headless browser for HTML→PDF and an Office-grade conversion service.

**Licensing (high level):** the app sends key, hostname and username to `POST /licenses/verify`. It stores the key, expiry and token in `%APPDATA%\sejda-desktop\prefs.json`. The Java side checks expiry and free-tier counters, and compares the clock against internet time.

### 10. Third pass: live verification ([live-verification.md](live-verification.md))

- **Local upload (observed):** `POST /api/files/upload-check` → `{"status":"ok"}`. Then a multipart `POST /api/files/upload?uplid=…` with header `X-FileLocalId` → `{"id":"<uuid>-<16>_2"}`. A plain PDF is accepted without the zip wrapping.
- **Download signature:** `s=web-<35 chars>`, issued once per task. It works as a **bearer link**: no cookies are needed until the file expires. `d=true` sets `content-disposition: attachment`, and `_s` is the backend node.
- **402 (observed):** `{"reason":"tasks-per-hour","code":"tasks-per-hour"}`, with `x-ratelimit-remaining: -1`. The free quota is counted **per IP**, not per cookie.
- **Captcha:** **Cloudflare Turnstile** (action `taskSubmit`), shown in a `/captcha` iframe. The token goes back through `captchaCallback` as `captchaToken` and is valid for 300 s.
- **Infrastructure:** the whole site is behind Cloudflare. Behind it is a pool of numbered origin nodes (`www23`, `www43`, `www60`… with no public DNS), pinned per session by the `_s` cookie. `JSESSIONID` points to a Java servlet backend.

**Still unknown:**
- the chunked-upload path, tested from code only
- the queued/processing poll payloads
- the 429/430 bodies (not provoked on purpose)
- how `s=` is computed
- the login form internals
- the queue, storage and conversion services behind the server-only features
- **S3 upload fields:** the AWS S3 POST fields on watermark/alternate-mix pages are present in the HTML but empty, and no S3 code was found in the bundles. They may be a legacy leftover.

---

### 11. Building your own version: recommendations (my suggestions, not observed)

**Confirmed by the desktop analysis:** Sejda's engine really is SAMBox (Apache-2.0) + Sejda SDK (AGPL) + proprietary modules. SAMBox or plain PDFBox, both Apache-2.0, gives you the same PDF core without the AGPL obligation. The proprietary jars must not be reused.

- **Don't copy Sejda's code, text, branding or obfuscated JS.** Re-implement the behaviour; the feature set and UX ideas are fair game.
- **Core engine:** Sejda's maintainers publish the open-source Sejda SDK (Java, AGPL-3.0, github.com/torakiki/sejda). It implements many of the same task names (merge, split by pages/bookmarks/size/text, rotate, extract, alternate mix, n-up…). AGPL means you must publish your server source if you use it. To avoid that, use permissive libraries instead: **pdf-lib** / **qpdf** / **PDFBox (Apache-2.0)**.
- **Other parts:**

  | Need | Option |
  |---|---|
  | Compression / grayscale | Ghostscript (AGPL) or qpdf + image re-encoding |
  | OCR / deskew | OCRmyPDF + Tesseract |
  | Word/PPT/Excel → PDF | LibreOffice headless |
  | PDF → Word/Excel | hardest part; commercial SDKs or pdf2docx / Camelot / Tabula |
  | HTML → PDF | headless Chromium (Playwright `page.pdf()`) |
  | Editor | PDF.js for rendering + your own operation model applied server-side (or with pdf-lib in the browser) |

- **Architecture to mirror:** upload → file id → `POST /tasks {type, files, options}` → async job queue → result page → auto-delete after N hours.

---

# Part 2: Agent 1, runtime capture in a real browser

> Live browser runs through REA: results page, polling, real request/response bodies, cookies, storage. (source: `agent-1-runtime.md`)

Observed 2026-10-21 with REA `capture_browser_scenario` (launch mode, headless Microsoft Edge 155 / Chromium, temp profile, en-US, UTC). REA performed the declared actions (clicks/fills) in the browser. Static findings in `SEJDA-REVERSE-ENGINEERING.md` are not repeated except where runtime confirms or corrects them.

**Load on Sejda:** 10 page-load scenarios, **2 tasks** in total (1 `compress`, 1 `edit`), both on a public 13 KB one-page test PDF (`https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf`). No paywall, captcha (430) or 429 was hit. After the 2nd task the server reported `x-ratelimit-remaining: 1`. No login, no fuzzing, and no hand-made API calls: every `/api` request below was made by Sejda's own UI.

**Key:** **[observed]** = seen in captured traffic, DOM or screenshot. **[inferred]** = deduced. **[unknown]** = not determined. Shipped-JS reads done to explain runtime behaviour are marked **[observed-js]** (`result.min.js?v=132` captured at runtime; `libs-and-partials.min.js` cache 649; `pdf-editor.min.obfuscated.js?v=523`).

**Redactions:** cookie values are hashed or redacted by REA. The page's `data-proxy-token` / `x-proxy-token` / `_xpt` value and the download signature `s=web-…` are shortened to `<…>` below.

### Evidence index

| ID | Scenario |
|---|---|
| `ev_fbd7ca667531975ccc7dd349c4f2f0420a768e8dfaf288c31856aa5321e5a9b1` | compress-pdf page load: network, storage, accessibility |
| `ev_fdff1b3a4c1672fa3d1938abba14bd1779e0bd3fca0a3cb0d34141c72b3b56b3` | compress-pdf upload dropdown opened (DOM) |
| `ev_2b73b02c4c22a912789369f6640af28f289f71968ea9efbe6187ac41c4783947` | "Web Address (URL)" modal opened |
| `ev_6a1631b86fae847020df6653e99230f8b64f4f10381dc0cb45cfe30bacc83173` | failed attempt (wait_for timeout, no task submitted) |
| `ev_d84e2f504edd7c54dfc57eff6d572520f549151f2a5de8ed4870bfd4373f3ec5` | same-host URL `sejda.com/assets/sample.pdf` rejected client-side ("Invalid web address") |
| `ev_2f62afc4587e448da7b9b86abc9abeacb29316b2deaa0d223773dc1140ed967e` | **full compress task**: import, /api/tasks, result iframe, poll, download (bodies and headers) |
| `ev_050e3c00d2f02bd4a103b07f6b87a991ac821c106d46a216b0c0960d06452a98` | pdf-editor opened with a PDF: runtime fetches |
| `ev_2b4d81096814cf1cf37872315fd8e4894c248074d2a190ef1dc4d79333a32472` | pdf-editor DOM (task-form, files[]) |
| `ev_6a6072096072df4af1ee376fbcab30d4e4a9f41ea57e8c4a12e99a7305153296` | failed editor attempt (wrong selector, no task submitted) |
| `ev_5145c7700f0a3a2ace285ac8da0c89fccf720090d5f8bae53fd339da35a7b083` | **full edit task**: add one text box, Apply changes, result |

---

### 0. Methodology limitation: local file upload

The REA scenario action set (goto/click/fill/press/select/check/wait) has **no set-input-files or drag-drop action**, so a local file could not be pushed into `<input type=file>`. As a result, **`/api/files/upload-check`, `/api/files/upload` and `/api/files/upload-chunked` were not exercised at runtime** **[unknown at runtime]**. Their static description stands.

Instead I used the UI's own **"Web Address (URL)"** import (compress) and the **`?files=[{"downloadUrl":…}]`** page parameter (editor). The site itself builds that parameter in `result.min.js` (`publish-gdrive` → `sign-pdf?files=`). Both paths register the file with a different endpoint, described in §2.1.

---

### 1. Results page (`result?id=…`)

#### 1.1 How it is opened [observed, ev_2f62afc4…, ev_5145c770…]

1. `POST /api/tasks` → 200, body = JSON string task id, e.g. `"YHLFMUJQ-202610211908"`.
   - **Task id format:** `<8 uppercase alnum>-<yyyyMMddHHmm>`, with the timestamp in the server's timezone (UTC+1/+2 vs the browser's UTC) **[inferred]**.
2. The top page URL hash becomes `#results-<taskId>` (e.g. `compress-pdf?#results-YHLFMUJQ-202610211908`).
3. An iframe named **`_results`** navigates to `https://www.sejda.com/result?id=<taskId>`.

#### 1.2 Scripts the result page loads [observed]

- `/cache/649/js/libs-and-partials.min.js` (shared bundle)
- `/js/pages/result.min.js?v=132`, loaded lazily via `<script data-src>`
- `https://a.sejda.com/js/pa-pTbOttubxy_kKIavRgNtA.js` (self-hosted analytics)
- `/css/index.min.css?v=409`, Font Awesome woff2 files, Atkinson Hyperlegible fonts, icons (`gdrive.png`, `onedrive.png`, `gdrive_plus_v5.png`)

The result page `<body>` carries these attributes [observed]:
- `data-download-server="www.sejda.com"`
- `data-proxy-token="<…>"`
- `data-pro-user="false"`
- `data-max-file-size="500"`
- `data-ipcountry="IN"`
- `data-www="www23.sejda.com"` (the backend node)

#### 1.3 Polling [observed + observed-js]

- **Endpoint:** `GET /api/tasks/<taskId>/change?_=<cache-buster ms>`. This is jQuery `$.get` with `cache:false`, so the request carries `X-Requested-With: XMLHttpRequest` and `Accept: application/json, text/javascript, */*; q=0.01`.
- **Interval** [observed-js, result.min.js]:
  - status `processing` or `queued`: next poll after **3 s** (`setTimeout(p, 3e3)`).
  - unexpected (non-object) response: Sentry message `"Task change: unexpected response"`, then retry after **10 s**.
  - HTTP error other than 404: retry after **10 s**.
  - **404**: show the "These files have expired" state and stop.
- **Status values:** `status` is compared lower-cased against `loading | queued | processing | completed | failed | expired` (CSS state blocks on the page). The server sends capitalised values: `"Completed"` was observed. `Queued`, `Processing` and `Failed` are inferred from the code **[inferred]**.
- **Run length:** in both runs the task had already completed by the first poll (about 2 s after submit), so **only one poll** was made **[observed]**.
- **Cookie:** the `/change` response sets a cookie (`set-cookie` present). The `JSESSIONID` cookie (HttpOnly, host `www.sejda.com`) appears after it **[observed]**.

**`/change` response, compress [observed, ev_2f62afc4…]:**
```json
{"status":"Completed","type":"compress","remark":"We compressed your file to 13 KB (5% less)",
 "resultFilename":"dummy.pdf","resultFileSize":12624,
 "resultFullUrlPattern":"www.sejda.com/api/tasks/YHLFMUJQ-202610211908/download/%7B%7Bfilename%7D%7D?s=web-<…>&d=true&_s=23",
 "warnings":[],"resultItems":["dummy.pdf"],"id":"YHLFMUJQ-202610211908"}
```

**`/change` response, edit [observed, ev_5145c770…]:**
```json
{"status":"Completed","type":"edit","resultFilename":"dummy.pdf","resultFileSize":12960,
 "resultFullUrlPattern":"www.sejda.com/api/tasks/HR2OF03R-202610211913/download/%7B%7Bfilename%7D%7D?s=web-<…>&d=true&_s=43",
 "warnings":[],"resultItems":["dummy.pdf"],"id":"HR2OF03R-202610211913"}
```

**Fields the code reads that did not appear in my two runs** [observed-js]:
- `upgrade.reason`: paywall on the result. It shows `#<reason>-reason`, hides the download, sets the cookies `upgradeReason`, `upgradeRefTask` and `upgradeReturnUrl`, and tracks `paywall`. `"timeout"` is one reason.
- `failureReason` and `failureReasonCode` (links to `/help#<code>`). The special text "File not found. Please reupload and try again." leads to "Session expired".
- `warnings[]` is shown as a list.
- `remark` is shown as a sub-title.
- No percentage/progress field exists; progress is only the status. On the first poll the client shows a "Taking longer than usual… up to 2 minutes" i18n string **[observed-js / console]**.

#### 1.4 Download URL formation [observed + observed-js]

```js
// result.min.js
function s(filename, change) {
  return (location.protocol + "//" + change.resultFullUrlPattern)
         .replaceAllEscaped(encodeURIComponent("{{filename}}"), encodeURIComponent(filename));
}
```

- **Download button:** `#download-btn` gets `href = https://www.sejda.com/api/tasks/<id>/download/<filename>?s=web-<sig>&d=true&_s=<n>` and `download=<filename>`.
- **Preview:** the result page creates an iframe whose `src` swaps `d=true` → `v=true` and appends `&_xpt=<data-proxy-token>`. This preview iframe was auto-loaded in both runs because `results.autoShowPreview` is not `"false"` by default **[observed]**:
  `GET /api/tasks/<id>/download/dummy.pdf?s=web-<…>&v=true&_s=23&_xpt=<…>`
- **Preview response headers** [observed]:
  - `content-type: application/pdf`
  - `content-length: 12620`
  - `cache-control: no-store, private`
  - `accept-ranges: bytes`
  - `x-frame-options: ALLOW` (Chromium rejects this value as invalid and logs a console error)
  - `x-robots-tag: noindex, nofollow, noarchive, nosnippet, notranslate`
  - no `content-disposition` in `v=true` mode
- **`d=true`** is the attachment-download variant. I did not click it **[inferred: likely adds Content-Disposition: attachment]**.
- **`_s=<n>`** matches the backend node in the task POST body: `_s=23` ↔ `"www":"www23.sejda.com"`, `_s=43` ↔ `www43`. So `_s` routes the download to the node that holds the file **[inferred, strongly supported]**.
- **`s=web-<35 chars>`** is a per-task download signature or secret **[inferred]**.
- **Rename:** `#rename-btn` rebuilds the URL with a new filename. The server accepts any filename in the path **[observed-js; server behaviour inferred]**.

#### 1.5 Other result-page endpoints [observed-js only, not called]

| Endpoint | Purpose |
|---|---|
| `DELETE /api/tasks/<id>` | "delete-task-btn" |
| `POST /api/tasks/<id>/allow` | allow support access after a failure |
| `POST /api/tasks/<id>/save-gdrive` | `{accessToken, filename}` |
| `POST /api/tasks/<id>/publish-gdrive` | `{accessToken, filename, returnEmail}` |
| `POST /api/tasks/<id>/share/link` | `{filename}` → `{url}` |
| `POST /api/tasks/<id>/share/email` | |
| `POST /api/tasks/<id>/request/completed` | completes a signature request |

Dropbox Saver and OneDrive saving work from `#download-btn`'s href. On completion the result page also:
- fires `taskProcessingCompleted` on the parent document;
- calls `parent.completedTask(id)`;
- increments `localStorage["tasks.success.counter"]`;
- sets `window.top.onbeforeunload` to warn "Task results may not be downloaded";
- schedules `w()` (close frame) after **2 h** (`72e5` ms), matching the file retention.

---

### 2. Requests and responses

**Common headers on `/api` XHRs** [observed]:
- `X-Requested-With: XMLHttpRequest`
- `Accept: application/json, text/javascript, */*; q=0.01`
- the session cookies (`clientId`, `_s`, `lang`, and later `JSESSIONID`)
- for POSTs, `Content-Type: application/json; charset=UTF-8`

**Common response headers:**
- `cache-control: no-cache, private, no-store, no-transform`
- `pragma: no-cache`
- `x-frame-options: SAMEORIGIN`
- `x-firefox-translate: disable`
- `permissions-policy: interest-cohort=()`
- `server: cloudflare` with `cf-cache-status: DYNAMIC`

There was no CSRF token header **[observed]**.

#### 2.1 Registering a remote file: `POST /api/files` [observed, ev_2f62afc4…, ev_5145c770…]

This is what the "Web Address (URL)" import and `?files=[{downloadUrl}]` use. The old static note `/api/files/client-view?url=` as the *import* endpoint was incomplete.

```
POST /api/files
Content-Type: application/json; charset=UTF-8
{"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}

200  application/json;charset=utf-8
{"id":"67145c07-e50a-4788-b4c1-a2e20ddbaf4e-2FD2ANI0IOKJMYQM_2"}
```

- **File id format:** `<uuid>-<16 uppercase alnum>_<n>` **[observed]**. Every task used the trailing `_2` **[unknown meaning]**.
- **Where it goes:** the id is added to the task form as a hidden `files[]` input (seen in the editor DOM, ev_2b4d8109…).

**Client-side URL validation** [observed, ev_d84e2f50… + observed-js]:
- rejects `file:`, `\`, and `X:\`;
- prefixes `http://` if there is no scheme;
- rejects a host equal to `location.host`, so **sejda.com's own `/assets/sample.pdf` cannot be imported**;
- rejects anything not http/https;
- rejects an empty path `/`;
- redirects `.googleusercontent.com/viewer/` URLs to the Google Drive import.

#### 2.2 Preview proxy: `GET /api/files/client-view?url=<enc>` [observed]

**Sequence:**
1. PDF.js first fetches the remote URL directly from the browser. The W3C file has no CORS headers, so this fails (console error).
2. The client falls back to `https://<data-download-server>/api/files/client-view?url=<encoded>` with the header **`x-proxy-token: <data-proxy-token>`**.
3. Response 200:
   - `content-type: application/pdf`
   - `content-length: 13264`
   - `content-disposition: attachment`
   - `content-security-policy: sandbox`
   - `accept-ranges: bytes`
   - `x-content-type-options: nosniff`
   - `x-robots-tag: noindex, …`
4. PDF.js then aborts the request after reading it (`net::ERR_ABORTED`, normal with `disableRange`).

**Client behaviour:** a 429 from this proxy sets a client flag "client-view proxy rate limited" **[observed-js]**.

**Token:** the proxy token was **identical across all sessions on 2026-10-21** (`d084db2b…`), so it is a site-wide or daily constant, not per-user **[observed / inferred]**.

#### 2.3 `POST /api/tasks`: compress [observed, ev_2f62afc4…]

```
POST /api/tasks
Content-Type: application/json; charset=UTF-8   (content-length 605)
{"type":"compress","outputFilenamePattern":"",
 "files":["67145c07-e50a-4788-b4c1-a2e20ddbaf4e-2FD2ANI0IOKJMYQM_2"],
 "uri":"/compress-pdf","failIfOutputSizeNotReduced":false,
 "userAgent":"Mozilla/5.0 (… HeadlessChrome/155.0.0.0 … Edg/155.0.0.0)",
 "cvts":"0.26","pdfjs":"bebd506c3","libsCache":"649",
 "consoleLogs":["Failed to get document from: https://www.w3.org/…/dummy.pdf UnknownErrorException: Failed to fetch"],
 "traceId":"tr-9851cd35-7b05-4341-957e-beba3b889b93","www":"www23.sejda.com"}

200  application/json;charset=utf-8
x-ratelimit-remaining: 2
x-ratelimit-wait: 3599
"YHLFMUJQ-202610211908"
```

**Runtime-only facts** (not in the static report):
- **`files` shape:** a **flat array of file-id strings**. It is *not* objects, and has no `files[]` key suffix after serializeJSON.
- **Telemetry fields:** every task body carries client telemetry: `uri`, `userAgent`, `cvts` (client version?), `pdfjs` (PDF.js build hash `bebd506c3`), `libsCache` (`649`), `consoleLogs` (recent console warnings and errors!), `traceId` (`tr-<uuid>`), and `www` (backend node from `<body data-www>`).
- **Unset options are omitted:** compress options such as `imageQuality` and `imageDpi` were **not sent** when "More options" was untouched. Only `failIfOutputSizeNotReduced:false` was present, so the server applies its defaults **[observed]**.
- **Quota headers:** `x-ratelimit-remaining` counts down per task (2 after the 1st, 1 after the 2nd). `x-ratelimit-wait` is the number of seconds until the hourly window resets (3599, then 3265) **[observed]**.

#### 2.4 `POST /api/tasks`: edit (one added text box) [observed, ev_5145c770…]

```
POST /api/tasks      (content-length 1448)
{"type":"edit","elapsedTime":16,"recovered":false,"outputFilenamePattern":"",
 "files":["13590f21-016c-48ad-b08f-636c1873def4-2CMKULNR542TRQS5_2"],
 "appendTextOperations":[{"text":"Hello REA","font":"Helvetica","fontSize":"10.00",
     "position":{"x":298,"y":654},"lineHeight":10,"color":"#000000",
     "bold":false,"italic":false,"pages":"1"}],
 "uri":"/pdf-editor",
 "editTextOperations":[],"imageOperations":[],"shapeOperations":[],"insertPageOperations":[],
 "deletePageOperations":[],"highlightTextOperations":[],"editHighlightOperations":[],
 "deleteHighlightOperations":[],"appendLinkOperations":[],"editLinkOperations":[],
 "deleteLinkOperations":[],"appendAttachmentOperations":[],"deleteAttachmentOperations":[],
 "appendEmbeddedFileOperations":[],"deleteEmbeddedFileOperations":[],
 "appendFormFieldOperations":[],"deleteFormFieldOperations":[],
 "appendDraw":[],"appendLine":[],"deleteImageOperations":[],"rotatePageOperations":[],
 "userAgent":"…","cvts":"0.27","pdfjs":"bebd506c3","libsCache":"649",
 "consoleLogs":["i18n key trailing dot: Taking longer than usual. …","Failed to get document from: … Failed to fetch"],
 "traceId":"tr-6f7c7a55-8690-4c8d-af4c-1546d1ee3047","www":"www43.sejda.com"}

200  x-ratelimit-remaining: 1   x-ratelimit-wait: 3265
"HR2OF03R-202610211913"
```

**New versus the static list:**
- **Extra operation arrays:** the body also has **`deletePageOperations`**, **`appendDraw`** and **`appendLine`**, plus `elapsedTime` (seconds in the editor) and `recovered`.
- **Every array is sent**, even when empty.

**Text op shape** [observed]:
- `position` is in **PDF points with a bottom-left origin**. y=654 on a ~842 pt page matches a click at about one third from the top **[inferred]**.
- `fontSize` is a string with 2 decimals.
- `pages` is a string page selector (`"1"`).
- `font` is a base-14 name (`Helvetica`) when there is no document font.

**Edit cost:** the edit task counted against the same hourly quota as compress (remaining went 2 → 1). The separate "3 free saves" counter was not surfaced **[observed for the shared counter]**.

#### 2.5 Status and download

See §1.3 and §1.4. No other status or progress endpoints were called **[observed]**.

**Endpoints not called:**
- `POST /api/tasks/<id>/cancel` was not called, because the modal was not closed **[unknown at runtime]**.
- `POST /api/files/<id>/touch` was **not** observed within about 50 s on the page **[observed absence within the window; interval unknown]**.

#### 2.6 Upload endpoints

`/api/files/upload-check`, `/api/files/upload?_s=&uplid=…` and `/api/files/upload-chunked` were not exercised (see §0) **[unknown at runtime]**.

The **`uplid`** is rendered into the page per load, e.g. `OSNWO10211904`: 5 letters plus MMddHHmm. The form `action` is `https://www.sejda.com/api/files/upload?_s=&uplid=OSNWO10211904` and the file input is `name="file"` **[observed DOM, ev_fdff1b3a…]**.

---

### 3. pdf-editor at runtime [observed, ev_050e3c00…, ev_5145c770…]

#### 3.1 Requests when a PDF is opened, in order

1. Page HTML.
2. `/css/index.min.css?v=409`.
3. `/cache/649/js/libs-and-partials.min.js`.
4. **`/js/pages/pdf-editor.min.obfuscated.js?v=523`**.
5. Analytics `a.sejda.com/js/pa-….js`.
6. `/cache/149/js/pdfjs/pdf.min.js`. Note the different cache number, **149**, from libs (**649**).
7. `POST /api/files {"url":…}` → `{id}`, which registers the server-side copy for the later task.
8. `/cache/149/js/pdfjs/pdf.worker.min.js`, started as a **dedicated Web Worker**.
9. Direct fetch of the PDF URL (fails on CORS) → `GET /api/files/client-view?url=…` (+ `x-proxy-token`).
10. `/css/pdf-editor/fonts.css?v=5` plus **12 self-hosted Google handwriting fonts** for typed signatures, under `/fonts/google/<family>/vNN/*.woff2|woff`:
    - Stalemate, Over the Rainbow, Caveat, Cedarville Cursive, Dancing Script, Give You Glory, Kristi, Mr De Haviland, Norican, Reenie Beanie, Satisfy, Zeyada.
11. Font Awesome `fa-brands-400`, `fa-light-300`, then `fa-regular-400` (when the text box toolbar appears).

**Rendering:**
- All page rendering is **client-side PDF.js** from the bytes served by `client-view` (or a local file).
- **No `/api` render or page-image endpoints** were called, and no `cmaps/` or `standard_fonts/` requests occurred for this simple Helvetica PDF **[observed]**.
- PDFs with CID or non-embedded fonts may trigger them **[inferred]**.

**Adding the text box made no network calls** besides the FA regular font. Typing made no calls either. The only call on save was `POST /api/tasks` **[observed]**.

#### 3.2 Editor DOM facts [observed]

- `#task-content[data-task="edit"][data-multiple-files="false"][data-free-max-file-size="100"]`.
- The task form (`.task-form`) holds hidden `type=edit`, `elapsedTime`, `recovered=false`, `outputFilenamePattern` and `files[]=<fileId>`. The submit button is `#save-pdf-btn` "Apply changes".
- Pages render as `.page-wrap.rendered` with `canvas.page`. The pages container is `#edit-pages-wrap`, not `#edit-pages`.
- The active tool sits on `#edit-pages[data-tool="text"]`. Text is the default tool.
- A new text box is a `.text-editable[contenteditable=true]` with a floating `#text-editable-menu`: bold, italic, size, font, colour, link, move, clone, delete.
- Modals in the DOM include `#removeUnusedTextPrompt` ("Found 'Type your text' edits…") and `#recoveryPrompt` ("Recover unsaved changes").

#### 3.3 Result

The edit task used the identical result-iframe, poll and download flow (§1). The output was 12,960 bytes vs 13,264 input **[observed]**.

---

### 4. Cookies, storage, third parties

#### Cookies (names only) [observed, ev_fbd7ca66…, ev_2f62afc4…, ev_5145c770…]

| Cookie | Domain | Flags |
|---|---|---|
| `clientId` | `.sejda.com` | SameSite Lax, not HttpOnly, not Secure. Set on first page load. |
| `_s` | `.sejda.com` | SameSite Lax, not HttpOnly. Set on first page load. Same name as the `_s=` query param **[inferred related]**. |
| `lang` | `www.sejda.com` | |
| `JSESSIONID` | `www.sejda.com` | **HttpOnly**. Appears after the task / `/change` response, which suggests a Java servlet backend **[inferred]**. |

The cookies `upgradeReason`, `upgradeRefTask` and `upgradeReturnUrl` are set only on a paywall result **[observed-js, not triggered]**.

#### localStorage keys [observed]

| Key | When set |
|---|---|
| `thumbnails-size` | page load |
| `agreedTerms` | page load |
| `prevUsedTools` | page load |
| `results.autoShowPreview` | after a task |
| `tasks.success.counter` | after a task |

Keys that appear only on certain UI actions **[observed-js, not triggered]**:
- `cfg.global.autoDownload`
- `feedback.saveTime.asked`
- `shareByEmailVerificationCode`
- `completeReqByEmailFrom`
- `completeReqByEmailVerificationCode`

sessionStorage was empty in all runs. `files` is written only for "continue with" chaining **[observed-js]**. The editor recovery store (`EditorRecovery`) did not appear in localStorage, so it may use IndexedDB **[unknown]**.

#### Third-party / other hosts contacted [observed]

- **`a.sejda.com`:** only `GET /js/pa-pTbOttubxy_kKIavRgNtA.js`, once per document, including inside the result iframe. **No analytics beacon request was observed** in the windows captured **[observed absence; beacon timing unknown]**.
- **`www.w3.org`:** only the test PDF I chose (browser CORS attempt).
- **Nothing else:** no Google, Sentry, FastSpring, Stripe or Dropbox requests on compress-pdf, pdf-editor or result pages without user interaction.
- **Cloudflare:** fronts everything (`cf-ray`, NEL `report-to a.nel.cloudflare.com`, but no NEL report was sent).

#### Other runtime notes [observed]

- Static assets are served with `cache-control: public, max-age=2678400` (31 days) from the Cloudflare cache (`cf-cache-status: HIT`).
- The shared bundle cache key is **649** (the static report saw 149, which is still PDF.js's cache path).
- Page HTML is `no-cache, private, no-store`.

---

### 5. Still unknown

1. **Upload endpoints:** request/response of `/api/files/upload-check`, `/api/files/upload`, `/api/files/upload-chunked`, the `X-FileLocalId` header, and the zip-wrapping on the wire. Not exercisable without a file-input action.
2. **Intermediate statuses:** the exact payloads of `Queued`/`Processing` (and `Failed`) from `/change`. Both tasks finished before the first poll. Payload shape is inferred from the code only.
3. **Header and parameter meanings:**
   - whether `d=true` adds `Content-Disposition: attachment` (not clicked);
   - the meaning of the `s=web-…` signature and of the file-id suffix `_2`;
   - whether `x-proxy-token` rotates (daily?).
4. **Untested endpoints:** `/api/files/<id>/touch` interval; `POST /api/tasks/<id>/cancel`; `DELETE /api/tasks/<id>` (not triggered).
5. **Error statuses:** 402/429/430 response bodies, which were deliberately not provoked.
6. **Editor extras:** editor recovery storage location; whether PDF.js `cmaps/`/`standard_fonts/` are fetched for complex PDFs; the server-side font for `appendTextOperations` when `font` is a document font id.
7. **Analytics:** what `a.sejda.com` analytics sends, and when.

---

# Part 3: Agent 2, static deobfuscation and payload schemas

> Editor fully deobfuscated: JSON schema of every operation, serialization, workflows, login, IndexedDB, analytics. (source: `agent-2-static.md`)

Date: 2026-10-21. Method: static parsing only. The target JavaScript was never executed: no eval, no node `require` of target files, and the obfuscator's own rotation IIFE was not run. Tooling: @babel/parser, @babel/traverse and @babel/generator, installed in the scratch workspace, plus REA.

Confidence key: **[seen]** = read directly in the deobfuscated or prettified code. **[inferred]** = deduced and not verified. **[unknown]** = not visible client-side.

Builds on `SEJDA-REVERSE-ENGINEERING.md`. This report corrects two points in it, marked **(correction)**.

### 0. Artifacts produced (scratch)

Workspace: `C:\Users\hp\AppData\Local\Temp\claude\e--coding-Sejda-copy\dc40d0aa-2b20-4fc6-985a-74a54080ae6b\scratchpad\agent-static\`

| File | What |
|---|---|
| `deobf.cjs` | Static deobfuscator (AST based) |
| `pretty.cjs`, `scan.cjs` | Prettifier; URL and analytics-call scanner |
| `out\pdf-editor.deobf.js` | **Deobfuscated and prettified editor** (6,436 lines). Every string-array call (9,900) is replaced and 1,681 dead wrappers are removed. |
| `out\pdf-editor.deobf.strings.json` | String array in its correct (rotated) order |
| `out\libs.pretty.js` | Prettified `libs-and-partials.min.js` (27,079 lines) |
| `out\page-{organize-pdf,rotate-pdf-pages,split-pdf,delete-pdf-pages}.pretty.js` | Per-tool page scripts. Fetched once from `/js/pages/*.min.js` with a 10 s delay between requests because they were missing (needed for Q4). |
| `out\libs.scan.txt`, `out\editor.scan.txt` | URL and analytics-event inventories |

Line numbers below (`L1234`) refer to `out\pdf-editor.deobf.js` (**E**) or `out\libs.pretty.js` (**L**). Byte offsets (`@123456`) refer to the original minified `libs-and-partials.min.js`.

REA: `analyze_javascript_application` (detail summary) on `agent-static\rea-app\` (the deobfuscated editor only):
- Evidence `ev_6177688f0e8c13264f0ece55c0f2c7dc159d48901357b1668a34c7622de4629d` (summary view)
- Parent evidence `ev_5f30f9e475e59a3895753f3339c3baec7a24dedb185e3bfab2d96b5fd5b83e4b`

It parsed 1 file and 58,374 AST nodes with 0 parse failures. It found 1,811 call-flow, 2,573 closure and 9,558 data-flow relations, and reported 0 request/fetch relations. That is expected, because all network I/O goes through jQuery `$.ajax` / `$.jsonPost` and form submit, which REA's request extractor does not model. The semantic coverage is "partial" (per-file node ceiling of 20,000). REA confirms the deobfuscated file parses cleanly; the schemas below come from reading the code.

### 1. Deobfuscation of `pdf-editor.min.obfuscated.js` [seen]

The script uses the javascript-obfuscator "string array + rotate + base64 + wrapper chain" profile:

- **String array:** `function a0n(){var wa=[…2070 strings…]; a0n=function(){return wa}; return a0n();}` at byte offset 0.
- **Decoder:** `a0N(index, key)` at @70968. It subtracts **0xBC (188)** from the index, base64-decodes with the alphabet `abc…xyzABC…XYZ0-9+/=`, URI-decodes, and caches. The second argument is unused, so this is the plain base64 variant, not RC4.
- **Top-level aliases:** `a0Xq(z,B) → a0N(B+0x221, z)` and `a0Xv(z,B) → a0N(B-0x2bc, z)`.
- **Wrapper chain:** every function scope declares 1–3 local wrappers such as `function wt(z,B){return wg(z-0x27f,B)}`. They chain several levels deep and swap or offset their arguments.
- **Rotation IIFE** at @55868: `(function(arr, 0x380dd){ while(true){ N = -parseInt(s1)/1 + -parseInt(s2)/2 + … ; if (N===0x380dd) break; else push(shift()) } })`.

**How I resolved it (no execution):**
1. Parsed the file with Babel, read the array literal, and base64-decoded each element myself.
2. Wrapper resolution: for each wrapper `function f(a,b){return g(<linear expr>, <linear expr>)}`, the callee `g` is resolved through Babel scope bindings. My own evaluator then follows the chain with constant +/- arithmetic until it reaches `a0N`, and computes `array[idx-188]`.
3. Rotation: I reimplemented the checksum expression from its AST, using my own `parseInt` over the decoded strings, for every shift `r` in 0..2069. Only **r = 182** gives `229597` (0x380dd). The resolved strings land at plausible call sites, for example `$(".task-form")`, `"appendTextOperations"` and `Analytics.trackNoPushEvent("pdf-editor-usage", …)`, which confirms the rotation.
4. Substituted 9,900 call sites with 0 failures. Then removed now-unreferenced wrappers, turned `x['prop']` into `x.prop`, and replaced `!0x0` / `![]` with booleans.

**Residue:** 13 dead wrapper functions remain. They are harmless and have no live callers.

**Anti-tamper finding [seen, E L182–L287, inside `Sejda.Fonts`]:** the code contains a javascript-obfuscator **domain lock**. It scans `window` for `document.domain` / `location.hostname` through charcode-matched property names, compares against an obfuscated allow-list (decodes to `.sejda.com`), and otherwise sets `location.href` to `about:blank`. A clone must not reuse this code anyway.

### 2. Editor save model (types `edit` and `fillSign`) [seen]

#### 2.1 Flow

1. The save button handler (E L4663–4690) offers to drop untouched default text boxes, then calls `cR(opts, cb)` (E L4788–5309).
2. `cR` walks the DOM and builds 25 arrays (list `cY`, E L4782). Every entry is a **JSON string**.
3. `cC(result)` (E L5310–5319):
   - removes old `<name>[]` hidden inputs from `form.task-form` and appends one hidden input per entry;
   - sets `elapsedTime` to seconds since editor load and `recovered` to true or false;
   - submits the form.
4. The generic submit handler in libs (L26545+, @779702):
   - serializes the form with `serializeJSON({parseAll:true})`;
   - for `type` in {`edit`, `fillSign`}, runs `JSON.parse` on every element of the 24 operation arrays (L26657);
   - unwraps `formValues = formValues[0]` and `formWidgets = formWidgets[0]`.
   - `tabOrder[]` and `formErrors[]` are not in that parse list, so they stay arrays of plain strings.

`deletePageOperations[]` is not built by `cR`. Hidden inputs for it are appended immediately when a page is deleted (E L4283) and removed on undo (E L3818).

#### 2.2 Coordinate system and units [seen unless noted]

- **Scale:** each `.page-wrap` has `data-scale = canvasCssWidth / page.getViewport({scale:1}).width` (E L3270–3277). That is CSS pixels per PDF unit at the current zoom.
- **Units:** every coordinate is computed as `(css px) / data-scale`, which gives **PDF user-space units (points, 1/72 in)**.
- **Origin is bottom-left:** `y = canvasHeight − top − height` (or `top = canvasHeight − offsetTop` for boxes). Coordinates are measured on the **displayed (rotated) viewport**. The viewport rotation is `page.rotate + data-user-rotation`. Mapping back to unrotated user space for pages with `/Rotate` is presumably done by the server **[inferred]**.
- **Bounding boxes:** `{left, top, bottom, right}` are integers, clamped to ≥ 0. They are accepted only if `top > bottom && left < right`. They are used for links, highlights, attachments, ink, lines and form fields.
- **Numeric types:**

  | Field kind | JSON type | Source |
  |---|---|---|
  | Image and shape `position`, `width`, `height`, `borderWidth` | strings (full precision) | Big.js values; Big.js `toJSON` returns a string (L6698) |
  | `fontSize` | string, `toFixed(2)` | |
  | `lineSize` and line `points` | strings, `toFixed(2)` | |
  | Text `position` | integers | rounded |
- **Colors:** `"#rrggbb"`, converted from CSS `rgb()`. A transparent or `rgba(0,0,0,0)` color becomes `undefined` and is left out of the JSON (`cv`, E L4597).
- **Page references:**
  - `pages` / `page` is `data-page-num`: the **current 1-based position in the editor**, renumbered after page inserts and deletes (`cB`, E L4216). It is a string.
  - `deletePageOperations` uses `data-original-page-num` instead.
  - So the server presumably maps deletes and inserts first **[inferred]**.

#### 2.3 Operation schemas (one JSON object per array entry) [seen]

Values are illustrative.

**appendTextOperations** (new text box, `.text-editable`, E L4795–4841):
```json
{"text":"Line 1\nLine 2","font":"Helvetica","fontSize":"12.00",
 "position":{"x":72,"y":700},"lineHeight":14,"color":"#000000",
 "bold":false,"italic":false,"pages":"1"}
```
- `font` is the CSS font-family name. If that font is not in the built-in list, the editor substitutes the name of the matching embedded document font (`findDocFontByFontFace`).
- `position` is the **baseline-ish** origin: the bottom of the box plus the descent computed by `measureText("Ag")`.
- `lineHeight` is (box height / lines) / scale.
- Entries are skipped when the text is empty.

**editTextOperations** (inline edit of existing text, E L4842–4901):
```json
{"originalText":"Old","text":"New","lineHeight":"14.00","font":"ArialMT",
 "fontId":"g_d0_f1","bold":false,"italic":false,
 "area":{"x":70,"y":95,"width":120,"height":26},
 "pages":"1","fontSize":"12.00","color":"#000000","position":{"x":72,"y":700}}
```
- `fontId` is the PDF.js font loadedName from the text layer (`data-font-id`).
- `area` is the whiteout or erase rectangle. It is padded by 6 px on each side and **uses top-left-origin CSS coordinates divided by scale** (floor for x/y, ceil for w/h), not bottom-left. Note this inconsistency.

**imageOperations** (images and signatures, including `.formLayer .signature img`, E L4904–4965):
```json
{"position":{"x":"100.5","y":"500.25"},"pages":"2","width":"150","height":"60",
 "rotation":0,"image":"<fileId | data:image/png;base64,…>","exceptPages":[],
 "signatureFieldName":"Signature1","anchorTop":"12.000","anchorBottom":null,
 "anchorLeft":"20.000","anchorRight":null}
```
- **`image`:** the server **file id** of an image uploaded with scope `editor-image` through the normal uploader (`data-file-id`, E L2018), or a data URL. When it is a data URL, `rotation` is forced to 0.
- **Repeat on all pages:** `pages:"1-"`; `exceptPages` lists the page numbers whose copy was removed. The `anchor*` fields hold the distance to the nearest page edges in points, so the server can re-position the image on pages of different sizes (E L1755–1780).
- **Rotation:** `rotation` is in degrees from `data-rotation`.
- **Missing images:** an image with an empty data URL is dropped and the user is alerted.

**shapeOperations** (rectangles, ellipses and the **whiteout** tool, E L4966–4994):
```json
{"position":{"x":"50","y":"400"},"pages":"1","width":"200","height":"40",
 "borderWidth":"2","borderColor":"#ff0000","backgroundColor":"#ffffff","shape":"rectangle"}
```
- `shape` is `rectangle`, or `ellipse` when a border-radius is set.
- Whiteout is a rectangle with white fill and white border, `borderWidth` 2 (E L1273).

**appendLine** (line and arrow annotations, E L4995–5035):
```json
{"page":"1","boundingBox":{"left":10,"top":300,"bottom":280,"right":200},
 "lineSize":"2.00","points":["0.00","20.00","190.00","0.00"],"color":"#000000","kind":"arrow"}
```
- `points` are x1, y1, x2, y2 relative to the bounding box, in points.
- `kind` comes from `data-kind` (line or arrow variants) **[values inferred]**.

**appendDraw** (freehand ink, E L5222–5246):
```json
{"page":"1","boundingBox":{…},"color":"#0000ff","inklist":[[x,y,…]],"appearance":{…},"lineSize":3}
```
- `inklist` and `appearance` come from the `data-inklist` and `data-appearance` JSON. Their inner shape is set by drawing code not traced here **[unknown detail]**.

**highlightTextOperations / editHighlightOperations / deleteHighlightOperations** (E L5192–5221):
```json
{"page":"1","boundingBoxes":[{"left":…,"top":…,"bottom":…,"right":…}],"color":"#ffff00","kind":"highlight|strikethrough|underline"}
{"page":"1","annotationId":"12R","color":"#00ff00"}
{"page":"1","annotationId":"12R"}
```
- There is one bounding box per entry.
- For strikethrough the color comes from the top border; for underline, from the bottom border.

**appendLinkOperations / editLinkOperations / deleteLinkOperations** (E L5036–5073):
```json
{"annotationId":"<present only for edit>","boundingBoxes":[{…}],"page":"1","kind":"uri|page","href":"https://…"}
{"page":"1","annotationId":"34R"}
```
- An entry goes to `edit…` when the link already exists (`annotationId` set), otherwise to `append…`.
- `kind`:
  - an `href` starting with `http`, `mailto:` or `tel:` becomes `uri`;
  - a numeric `href` ≤ numPages becomes `page`;
  - `mailto` becomes `uri` with a `mailto:` prefix;
  - `tel` becomes `uri` pointing to `https://www.sejda.com/call/<encoded number>` (a redirect service).

**appendAttachmentOperations / deleteAttachmentOperations** (file-attachment annotations, E L5074–5106):
```json
{"boundingBoxes":[{…}],"page":"1","filename":"invoice.xlsx"}
{"page":"1","annotationId":"40R"}
```

**appendEmbeddedFileOperations / deleteEmbeddedFileOperations** (document-level embedded files, E L5107–5119):
```json
{"file":"<uploaded file id>"}
{"filename":"old.txt"}
```

**appendFormFieldOperations / deleteFormFieldOperations** (form creator, E L5120–5178):
```json
{"kind":"text|checkbox|radio|select|signature|…","name":"Field1",
 "boundingBox":{"left":…,"top":…,"bottom":…,"right":…},"page":"1",
 "selected":false,"multiline":false,"required":false,"value":"abc",
 "options":"Opt A\nOpt B","multiselect":false,"borderColor":"#000000","color":"#000000",
 "fontSize":12,"align":"left","id":"ff-…","combChars":10,"maxLength":20}
{"page":"1","objId":"55R"}
```
- `textarea` becomes `kind:"text"` with `multiline:true`.
- `combChars` and `maxLength` are only present for text fields.
- `options` is the option texts joined with `\n`.
- `fontSize` is only present when the user set it.
- A modified existing field is sent as **delete (objId) + append**.

**insertPageOperations** (E L5179–5184):
```json
{"page":"3"}
```
This is the position of the new blank page in the final order. The blank template is `#new-page-template`, sized from page 1 **[seen L2341]**.

**deletePageOperations** (E L4283):
```json
{"page":"5"}
```
The page number is the **original** one.

**rotatePageOperations** (E L5266–5275):
```json
{"pages":"2","degrees":90}
```
- `degrees` is normalized to 0–359, accumulated in ±90 steps.
- Rotation is refused on pages that already have edits.

**deleteImageOperations** (existing image XObjects, E L5249–5258):
```json
{"page":"1","objId":"17R"}
```

**formValues** (single object after unwrapping):
```json
{"<fieldName>":"value"}
```
- Checkbox `false` becomes `"Off"`; arrays and objects are joined with `"|||"`.
- Text values are cleaned of control characters; newlines are kept for multiline fields.
- The source is `globalPdfJS.FormFunctionality.getFormValues(filter data-changed=true)`, a Sejda-patched PDF.js. It is only sent when there is at least one changed field.

**formWidgets:** the widget map from the same call. Its shape is **[unknown]** because it lives inside Sejda's PDF.js build, which was not analysed.

**formErrors[]:** strings.

**tabOrder[]:** an array where the index is `tabindex` and the value is an existing `objId` or the new field DOM id. It is only sent when `Sejda.TabOrder.hasChanges()`.

#### 2.4 Final `/api/tasks` body for the editor [seen]

```json
{
  "type": "edit",                // "fillSign" on /sign-pdf
  "files": ["<fileId>"],         // exactly one
  "elapsedTime": 154, "recovered": false, "outputFilenamePattern": "",
  "appendTextOperations": [{…}], "editTextOperations": [], "imageOperations": [], "shapeOperations": [],
  "insertPageOperations": [], "deletePageOperations": [], "rotatePageOperations": [],
  "highlightTextOperations": [], "editHighlightOperations": [], "deleteHighlightOperations": [],
  "appendLinkOperations": [], "editLinkOperations": [], "deleteLinkOperations": [],
  "appendAttachmentOperations": [], "deleteAttachmentOperations": [],
  "appendEmbeddedFileOperations": [], "deleteEmbeddedFileOperations": [],
  "appendFormFieldOperations": [], "deleteFormFieldOperations": [],
  "appendDraw": [], "appendLine": [], "deleteImageOperations": [],
  "formValues": {…}|undefined, "formWidgets": {…}|undefined, "formErrors": [], "tabOrder": [],
  "uri": "/pdf-editor",
  "userAgent": "…", "cvts": "3.42", "pdfjs": "<build>", "libsCache": "649", "consoleLogs": […],
  "traceId": "tr-<uuid>", "www": "<body data-www>", "ipclient": "<body data-ipclient>", "promo": "…",
  "captchaToken": "…"            // only on resubmit after HTTP 430
}
```

- **Empty arrays:** because the inputs are hidden `name[]` fields, an operation type with no entries is **absent** from the body, not an empty array **[inferred from serializeJSON behaviour]**.
- **Telemetry fields:** `userAgent`, `cvts` (minutes on page), `pdfjs`, `libsCache`, `consoleLogs`, `traceId`, `www`, `ipclient` and `promo` are added to **every** task (L26744, @789667).

**Remote signing (sign-pdf)** [seen E L6380–6418]:
- `POST /api/sign/link` with `{emailRequester, fileId}`. The response is `{signUrl}`.
- `POST /api/sign/email` with `{emailTo, emailFrom, message, fileId}`.
- Both are serialized with `parseAll`. A 400 response text is shown to the user; a 429 means "too many".

**Form-field detection [seen E L6280–6310]:**
- `POST /api/files/<fileId>/process/detect-form-fields` with `{pageNum: <original page>}`.
- The response is `{status, fields, failureReason}`.
- The client shows a slow notice after 40 s and the request can be cancelled.

**Crash recovery [seen E L6095–6200]:**
- **Storage:** a Dexie (IndexedDB) database `pdf-editor-recovery_v2`, store `sessions: "id,file,added,formData"`.
  - `id` = session start timestamp; `file` = `"<name>:<size>"`; `added` = timestamp.
  - `formData` = JSON of the `cR` result, with images as data URLs capped at 800×800.
- **When it saves:** after 5 minutes of inactivity, only if there are at least 5 operations, and on `uploadAgainNotPossible`.
- **Cleanup:** entries are purged after 48 h, and on `taskProcessingCompleted`.
- **Restore:** feeds the saved data straight into `cC` with `recovered:true`.
- **Old database:** the legacy database `pdf-editor-recovery` is deleted.

**Fonts [seen E L182–300; pdf-editor.html]:**
- **Built-in families:** Liberation Sans/Serif/Mono, Helvetica, Times New Roman, Courier New, Arimo, Carlito, Caladea, DejaVu Sans/Serif, Noto Sans/Serif (and Chakma, Tamil), Open Sans (and Condensed), Roboto, Lato, Inter, Poppins, PT Sans/Serif families, EB Garamond, Fira Sans, Droid Serif, Amiri, Scheherazade New, Oranienbaum and Selawik.
- **Metric-compatible substitution map:** Arial → Liberation Sans, Calibri → Carlito, Cambria → Caladea, Verdana/Tahoma → DejaVu Sans, Times* → Times New Roman, Courier* → Courier New, Segoe UI → Selawik, Trebuchet MS → Fira Sans, and so on.
- **Subset prefixes:** a prefix such as `ABCDEF+` is stripped before name matching.
- **What the server receives:** only the font **name** string, plus `fontId` for edits. No font bytes are sent.

### 3. libs-and-partials: form serialization and platform services

#### 3.1 `form.task-form` → `/api/tasks` [seen, L26545–26745]

- **Serialization:** jquery.serializeJSON 2.x with **`{parseAll:true}`**. Numeric strings become numbers, `"true"`/`"false"` become booleans and `"null"` becomes null. So `pages:"5"` arrives as the number **5**, while `"1-5,8"` stays a string. Names ending in `[]` become arrays, and `a.b` / `a[b]` become nested objects.
- **Transport:** `$.jsonPost` = POST with `Content-Type: application/json; charset=utf-8` and `dataType: json` (@644729).
- **Submit guards:**
  - a double submit within 2 s is rejected;
  - `runFormValidators` must pass;
  - the client waits while `PdfFiles.filesUploading > 0`, with a 5-minute timeout.
- **`files`:** an array of server file ids from hidden `files[]` inputs, nulls filtered out. It is natural-sorted by filename unless the user reordered files (`filesNaturalSorted=false` is then removed from the body).
- **Passwords (correction):** they are **not** in the task JSON. The password prompt sends `POST /api/files/<id>/password {password}` as soon as both the id and the password are known (L24526–24600, @711632). "Use for all files" reuses the same password. For owner passwords, the client validates locally with PDF.js (`checkOwnerPwd`) before accepting.
- **Per-type post-processing [seen]:**

  | type | Extra fields built by JS |
  |---|---|
  | `splitByPages` | `step` from `#splitStep`; `specificResultFilenames[]` (one per selected cut mark, may be "") |
  | `merge` mode `file` | `files[]` in visual order, `rotations[]` (deg per file), `images[]` (ids of non-PDF inputs) |
  | `merge` mode `page` | becomes **`combineReorder`** (see §4) + `images[]` |
  | `alternateMix` | `files[]`, `step[]`, `reverse[]`, `repeat[]` (bool) per file; needs at least 2 files |
  | `extractPages` | `pages` = active preset radio (e.g. odd/even) |
  | `splitByBookmarks` | `bookmarksLevel` from the active button |
  | `rotatePages` | `pageRotationsPerSource[]` (see §4) |
  | `crop` (manual) | `area`, or `oddArea` + `evenArea`, or `pageAreas{pageNum: area}` (areas JSON from `data-area`) |
  | `pdfToImage` | `allPages=true` → `pages:"1-"` |
  | `watermark`, `editBookmarks` | `jsonData` is parsed and **merged into the top level** |
  | `pdfToExcel` | `tables[]` JSON-parsed |
  | `jpgToPdf` | `files[]`, `rotations[]` in visual order, `mergeOutputs`, `pageSizeCustomWidth/Height` |
  | `htmlToPdf` | keeps only one of `files` / `urls` / `htmlCode` by active tab; `viewportWidth` defaults to window width; `scrollPage:true` with urls |
  | `encrypt` | `userPassword`, `ownerPassword` read directly |
  | `editMetadata` | `metadata{Key: value}`; CreationDate/ModDate `dd/mm/yyyy, hh:mm:ss` converted to **epoch ms** |
  | `renameByText` | `areas` JSON-parsed |
  | `deskew` manual | `angles` JSON-parsed (`{page: angle}`) |
  | `compress` with linked (cloud/url) files | `failIfOutputSizeNotReduced:false` |
- **Every task** also gets `uri` (the tool path, e.g. `/merge-pdf`) plus the telemetry fields from §2.4.
- **Responses:**
  - 200: `showResultsModal(taskId)` sets the hash and opens the result iframe. It also reads the `X-RateLimit-Remaining` and `X-RateLimit-Wait` headers.
  - 402: paywall `{reason}`, with a countdown when the reason is `tasks-per-hour`.
  - 430: captcha.
  - 429: too many requests.
  - 400: the response text is shown.
  - 0: offline.

#### 3.2 Workflows [seen, L23772–23930, @685838; L26756–26810]

- **Storage:** a Dexie database `workflows`, stores `workflows: "id,data"` and `blobs: "id,blob"`. The workflow data is a JSON string:
```json
{"id":"3RMYJG3C-202309291715W","name":"Example Workflow","addedDate":1696000000000,
 "steps":["Flatten","Compress"],"taskTypes":"flatten-compress",
 "tasks":[{"uri":"/flatten-pdf","type":"flatten","flattenMode":"all","files":[]},
          {"uri":"/compress-pdf","type":"compress","files":[],"failIfOutputSizeNotReduced":false}]}
```
- **What a step is:** each task is the exact `/api/tasks` body that was captured (`window.lastTask`), with `files` cleared and the telemetry fields (userAgent, cvts, pdfjs, libsCache, consoleLogs, traceId, www) deleted.
- **Ids:** 8 random chars from an alphabet without I/L/O/0, then a timestamp `yyyymmddhhmm`, then a trailing `W`.
- **Recording:** `Sejda.WorkflowRecorder` keeps the in-progress chain in **sessionStorage `workflow`**. "Continue with another tool" appends `lastTask`. A workflow holds 1–10 tasks.
- **Unsupported step types:** `htmlToPdf`, `edit`, `fillSign`, `combineReorder`, `rotatePages` and `pdfToExcel`, because they depend on interactive page state.
- **Running a workflow:** `form.workflow-form` with `#workflowId`, on `/workflows`. For step n:
  1. Load the task and set `workflowId` and `workflowStep`.
  2. Set `files` to the currently uploaded ids, then apply per-type fixes (merge `images`; jpgToPdf/alternateMix check file counts).
  3. Submit it as a normal task.
  4. When the result iframe dispatches `workflowTaskCompleted` (detail: `{warnings, resultFilesParam}`), clear the files, re-open the results as link files (`openFilesFromWorkflowStep`) and run step n+1 after 1 s.
  5. The chain stops on warnings.
- **Export/import:** `{format:"workflows-v1", timestamp, data}`. `data` is base64 of (12-byte IV + AES-GCM-256 ciphertext). The key comes from PBKDF2-SHA256 with 1,000 iterations, using a **key and salt hard-coded in the JS** (charcodes offset by 7). This is obfuscation, not security (`Sejda.Crypto`, @635838).
- **Default:** if the user has no workflows, an example workflow (flatten → compress) is shown.

#### 3.3 Login, account and session [seen, L24400–24500, @707350/@708417]

- **Login UI:** login is an iframe page `login` shown in the results modal (`showLoginModal`). On success the iframe calls `window.top.userLoggedInHandler(email, teamMember)`, which:
  - sets `body[data-pro-user=true][data-logged-in-user][data-team-member-user]`;
  - hides ads and the upgrade popup;
  - re-enables submit;
  - reloads the result iframe;
  - triggers `userLoggedIn`.
- **Session:** a cookie session. The `User_Ticket` cookie is on `.sejda.com`.
- **Single-device enforcement:** the backend sets `User_AutoLogout`. The page polls every 5 s; when that cookie appears, it logs out locally and shows "logged in on a different device".
- **Logout:** `POST /users/logout {}`. It also:
  - removes the cookies;
  - clears local and session storage;
  - **deletes all Dexie databases**;
  - signs out of Google `gapi.auth2`.
- **Google sign-in:** Google Identity Services and a Google OAuth client id are present. The actual login form is in the iframe **[unknown]**.
- **Paywall cookies:** `upgradeReason` and `upgradeRefTask`, valid for 2 h. Server-side state comes from `body` data attributes such as `data-www`, `data-ipclient`, `data-ipcountry`, `data-download-server` and `data-proxy-token`.

#### 3.4 Recent files (IndexedDB) [seen, L25840–26035, @755168]

- **Storage:** a Dexie database `recent-files`. Version 1 has the store `recentFiles: "id,name,mimeType,createdTime,folderId,cachedAt"`; version 2 adds `source,filesParam,taskUri`.
- **Two sources:**
  - `source:"gdrive_app_folder"`: up to 50 files from the user's Google Drive folder **`SejdaPDF`**, listed with Drive v2 `files.list`.
  - `source:"sejda_task_result"`: added by `Sejda.RecentFiles.addRecentTask({id: taskId, resultFilename, name, resultFilesParam, taskUri, resultDlUrl})`. This is called from the results iframe.
- **Task-result records:** `filesParam` is JSON of link-file descriptors and `downloadUrl` is the result URL. They are purged 50 minutes after creation.
- **Deleting a record:** removes it locally and calls `DELETE /api/tasks/<id>`.
- **Panel:** `localStorage general.recentFilesPanel.dontShow` hides the panel.

#### 3.5 Cloud import/export [seen, L23980–24210, L25495–25585]

All cloud picks become **link files**. They are not uploaded from the browser. Instead the client calls `POST /api/files {url: link}`, and the response is `{id, pages, passwordProtected}` (`FileUploadPreChecksUrlBased`, @714623). A cool-down of 10 s applies; a 429 response shows the files-per-hour paywall.

**Correction:** the URL import endpoint is `POST /api/files {url}`. `/api/files/client-view?url=` is only a CORS proxy used for **previewing** with PDF.js. It goes to `https://<data-download-server>/api/files/client-view` with the header `x-proxy-token`.

| Provider | Flow |
|---|---|
| **Google Drive** | **Auth:** GIS token client, scopes `drive.file drive.install`. Re-consent is forced if `drive.file` is missing. The token is stored encrypted in localStorage `gDrive.token` with `expires_at`. **Picker:** Google Picker with team drives and list view. **Link:** the file's `downloadUrl` or `exportLinks`, rewritten to `www.googleapis.com`, with the token and `originalFilename` appended as query parameters (`mapGdriveFileToSejda`). **Errors:** `restricted_access` is handled. |
| **Dropbox** | Dropins Chooser, `linkType:"direct"`, filtered by the tool's extensions, multiselect when the tool allows it. `expires_at` = now + 4 h. |
| **OneDrive** | OneDrive.js v7.2 `OneDrive.open` with `action:"download"` and redirect `/one-drive-auth`. **Link:** `@microsoft.graph.downloadUrl` with query parameters `originalFilename`, `expires_at` and `oauth_bearer`. The bearer is dropped for `*.microsoftpersonalcontent.com` and `*.sharepoint.com`. |
| **URL / web integration** | A URL prompt. Also `?files=[{downloadUrl,originalFilename,title}]` or sessionStorage `files`; only http(s) is allowed, and `data-external-integration=false` blocks it. "Open blank doc" uses `/assets/new_document.pdf`. |
| **Consent** | `Sejda.OptOutChoices.askDropbox()` and `askMicrosoft()` gate the loading of third-party scripts. |

Export to Drive, Dropbox or OneDrive happens in the results iframe page, which is not available **[unknown]**. Google Drive results presumably go into the `SejdaPDF` folder **[inferred]** from listAppFolderFiles.

#### 3.6 Captcha [seen L26835–26840, @793604]

- **Trigger:** HTTP 430. The client stores the body in `window.lastCaptchaFormData` and opens the iframe page **`captcha`** in the results modal.
- **Callback:** that page calls `window.top.captchaCallback(token)`, which resubmits the same body with `captchaToken`.
- **Provider [unknown]:** no hCaptcha, reCAPTCHA or Turnstile strings appear in any downloaded page or bundle, so the provider lives only in the `/captcha` page.

#### 3.7 Analytics [seen, L22341, @639371]

- **API:** `Analytics.trackEvent(name, category, label, value)` calls **Plausible** `plausible(name, {props:{event_category, event_label, value}})`. The Plausible script is self-hosted as `a.sejda.com/js/pa-….js`. `trackNoPushEvent` only appends to an in-memory list.
- **What the list is used for:** it is attached to bug reports and Sentry. Inside iframes, events are forwarded to the top window.
- **Error reporting:** Sentry/Raven goes through `/sentry-tunnel`; JS errors are also sent to `POST /errors/js?_s=1`.

**Pushed (Plausible) events:**
- `taskSubmitFailed` (Invalid inputs, No files, No pages, Duplicate filenames, File missing, No images selected, No pages rotated, Not enough files, Offline, Server rejected, Slow down, No files upload modal)
- `paywall` (reason, task)
- `workflows` (execute, execute-step, execute-rejected)
- `gdriveBlocked`, `gdriveFilesOpen`, `gdriveFilesFailed`
- `fileUploadFailed`, `touchFileFailed`, `uploadAgainModalShown`
- `image-conversion`, `pdfjs` (failed_loading, unsupported_feature), `formInvalid`
- `promo`, `share`, `ssl-failure`, `unauthorizedClient`
- `webIntegration` (open, blocked), `error unknownExtension`
- In the editor: `perms edit pro|free`, `editorFont`

**Non-pushed events:**
- `taskSubmit`, `taskCaptcha`
- `file-upload` (started, done, chunked, chunked-parallel), `fileOpen` (paste, url, gdrive, dropbox, onedrive)
- `file reuploaded`, `uploadAgain`, `uploadAgainNotPossible`, `logged-in-handler`
- `online`, `offline`, `ssl-ok`, `js.error`, `capturedException`, `capturedMessage`, `perms unlocked`
- In the editor, about 90 `pdf-editor-usage <tool> <action>` events: text-tool, image-tool, sign-tool, signature-tool, shape-tool, line-tool, draw-tool, highlight-tool, link-tool, ff-tool, ff-detect, attachments, whiteout-tool, undo-tool, tab-ordering-tool, publish-form, insert-page, delete-page-tool, font-replacement, scanned-doc and others. The full list is in `out\editor.scan.txt`.

### 4. Page selection and thumbnails (organize / rotate / delete / split) [seen]

- **Thumbnail element:** each thumbnail is `li.pdf-page-wrap[data-page=<1-based page>][data-file-counter=<client file counter>][data-filename][data-rotation]`.
- **Element id:** `pdfPageWrap<page>f<counter>` (L24995–25015).
- **Mapping counters to ids:** the file counter is mapped to the server id with `Files.idByCounter`.
- **Per-page tools (enabled by `#task-content` data attributes):** `data-can-reorder/-delete/-bulk-delete/-rotate/-select/-select-multiple/-duplicate/-move`. Selection supports click, Ctrl and Shift ranges, plus select all, none, odd, even and inverse.
- **Rotation steps:** each click adds ±90 and normalizes with `(cur+delta+360)%360`, giving 0/90/180/270.
- **Selection → `pages` string** (`selectedPagesChanged`, L26200, @767872): the selected `data-page` values are compressed into ranges such as `"1-3,7,9-10"` and written to `#specificPages` (`name="pages"`). For **splitByPages** they are not compressed: the value is a comma list of the pages **after which** to split, taken from the selected cut marks.
- **Encodings by tool:**

  | Tool | Encoding sent |
  |---|---|
  | **delete-pdf-pages** (`deletePages`) | Deleting thumbnails accumulates page numbers into `pages` as compressed ranges, e.g. `"2-4,9"` (page script). Also `discardOutline`. |
  | **extract / pdf-to-jpg / etc.** | `pages` range string. Presets: `odd`, `even`, `all`, `1-`. An open range like `100-` means to the end. |
  | **split-pdf** (`splitByPages`) | `step` (every N pages; burst = 1; preset every 4) **or** `pages:"3,7,10"` (split after these), plus `specificResultFilenames[]` aligned to the cut marks. "every-even-page" sets `pages:"even"`. The `outputFilenamePattern` tokens are `[BASENAME] [CURRENTPAGE] [TIMESTAMP] [FILENUMBER] [BOOKMARK_NAME] [BOOKMARK_NAME_STRICT] [TEXT]`. |
  | **rotate-pdf-pages** (`rotatePages`) | `pageRotationsPerSource: ["<fileIndex>:<page>:<degrees>", …]`. `fileIndex` is the index into `files[]`; only pages with non-zero rotation are listed; the payload is rejected if none are. Bulk buttons can apply to all, odd or even pages. |
  | **organize-pdf** and **merge (page mode)** (`combineReorder`) | `filePages: ["<fileIndex>:<page>:<rotation>", …]` in the **final visual order**. A blank page is `"-1:-1:<rotation>"`. The same source page used twice duplicates the file id in `files[]` and points at the new index ("avoiding input reuse"). `images[]` lists non-PDF inputs. Also `outputFilename`. |
  | **merge (file mode)** | `files[]` in order, `rotations[]` per file. |
  | **crop** | Per-page `pageAreas{page: {…}}` or `area` / `oddArea` / `evenArea`, from the thumbnail selection boxes. |

Examples:
```json
{"type":"rotatePages","files":["fA","fB"],"pageRotationsPerSource":["0:1:90","0:3:180","1:2:270"],"outputFilenamePattern":""}
{"type":"combineReorder","files":["fA","fB","fA"],"images":[],"outputFilename":"",
 "filePages":["1:1:0","0:2:90","-1:-1:0","2:2:0"]}
{"type":"splitByPages","files":["fA"],"step":"","pages":"3,7","specificResultFilenames":["part-a",""],"outputFilenamePattern":"[BASENAME]-[CURRENTPAGE]","discardOutline":true}
{"type":"deletePages","files":["fA"],"pages":"2-4,9","discardOutline":true}
```

Page numbers in these strings are 1-based **[seen: thumbnail label "Page a of"]**. The rotation in combineReorder and rotatePages is absolute (0/90/180/270), applied **relative to the page's existing /Rotate** **[inferred]**.

### 5. Still unknown

- **Results page:** the results iframe (`/result?id=`) and how it polls progress. That page also holds the export to Drive, Dropbox or OneDrive, the `addRecentTask` call and `workflowTaskCompleted` payload details. **[unknown]**
- **Captcha:** the provider and how the token is produced (only in the `/captcha` iframe page). **[unknown]**
- **Login form:** the iframe login (email/password, Google one-tap). Endpoints other than `/users/logout` are **[unknown]**.
- **Form data shapes:** `formWidgets`, the inner shape of `formValues` for radio and checkbox groups, and the `appendDraw.inklist` / `appearance` formats. These are produced by Sejda's patched PDF.js (`FormFunctionality`), which was not downloaded or analysed. **[unknown]**
- **Server conventions:**
  - whether the server interprets `pages` in edit operations against the post-insert/delete numbering, which the client strongly implies **[inferred]**;
  - how it handles coordinates on pages with an existing /Rotate **[inferred]**;
  - the meaning of the `appendLine.kind` values **[unknown]**.
- **`blobs` store:** what the `blobs` store in the `workflows` database is used for (no writer seen). **[unknown]**
- **Server-side validation:** how strictly the server validates JSON types. parseAll turns `pages:"5"` into the number 5, so the server must accept both. **[inferred]**
- **Other per-page scripts:** the per-tool scripts for the other tools (merge, crop, watermark, rename, deskew, etc.) were not fetched. Their `jsonData` / `areas` / `angles` inner shapes are **[unknown]** beyond what libs shows.

---

# Part 4: Agent 3, Sejda Desktop teardown (the engine)

> Sejda Desktop 7.9.11 unpacked statically: Java engine stack, jar inventory, task → engine class map, licensing flow. (source: `agent-3-desktop.md`)

Analysed on 2026-10-21. Nothing was installed or executed: the official portable ZIP was unpacked with `unzip`, `app.asar` was unpacked with a small Python reader, and jar contents were listed (manifests, `pom.xml`/`pom.properties`, config XML, class names and constant-pool strings only). No large-scale decompilation was done.

Confidence key: **[seen]** = read directly in the shipped artifact. **[inferred]** = deduced from names or strings. **[unknown]** = not determinable statically.

Builds on: [SEJDA-REVERSE-ENGINEERING.md](SEJDA-REVERSE-ENGINEERING.md) (web analysis).

---

### 1. Artifact identity

| Item | Value |
|---|---|
| Download page | `https://www.sejda.com/desktop` → `/js/pages/desktop.min.js?v=26` builds `"https://downloads.sejda-cdn.com/" + releases[platform]` [seen] |
| Files downloaded (official CDN `downloads.sejda-cdn.com`) | `sejda-desktop_7.9.11_x64_portable.zip`: 342,642,099 bytes, SHA-256 `4f5fcc4e75dcfb05c37244f3ef4c2c2adea9c31de477988e23361c51d6127b78` (Last-Modified 2026-08-28) |
| | `sejda-desktop_7.9.11_x64.msi`: 343,183,360 bytes, SHA-256 `6fef2143b8d06b4163a278560cf73cf80efc9aaff2283986802e7ef92bf61751` (downloaded and hashed only; no 7-Zip was available to unpack it, and the portable ZIP has the same build) |
| Other platforms listed | mac 7.9.10 `.dmg` (Intel and arm64), Linux 7.9.10 `.deb`/`.rpm` [seen in `desktop.html`] |
| App version | `package.json`: `sejda-desktop` **7.9.11**, identifier `com.sejda.sejda-desktop`, author "Sejda BV", MSI upgradeCode `ff3847d5-093c-4a09-8741-f214311a8bb7` [seen] |
| Main exe | `Sejda PDF Desktop.exe`: 232,336,064 bytes, SHA-256 `3756b0bf729b8ff006a908f5e9914e7629212600817c1a804fc715a3007f3eeb` |
| `resources/app.asar` | 47,705,715 bytes, SHA-256 `b2ec03f6700fa23e7a2120de2a76f3069a08efc547288502b080cc53395bfea4` |
| Local copies | `C:\Users\hp\AppData\Local\Temp\claude\e--coding-Sejda-copy\dc40d0aa-2b20-4fc6-985a-74a54080ae6b\scratchpad\agent-desktop\` (`download\`, `extracted\`, `asar\`, `tools\`) |

### 2. Architecture

```
Electron 42.4.0 shell  (Sejda PDF Desktop.exe; UI = EJS pages, same jQuery front end as sejda.com)
  renderer (contextIsolation on, nodeIntegration off; preload has sandbox:false)
    window.sejdaContext.general.desktopLauncher.execute(taskJson, cb)   <- exposed by preload.js
      lib/desktop-launcher.js  (runs in the preload's Node context)
        1. write %TEMP%\<tmp>\task.in      (task JSON: the same {type:"compress", files:[...], ...} as the web /api/tasks)
        2. write args.txt  "task.in=…\ntask.out=…\ntask.kill=…"
        3. child_process.spawn(resources\vendor\jdk25-windows-x64\bin\java.exe,
              [--add-opens…, -Xmx<60% RAM, max 8 GB; 2 GB for edit/fillSign>,
               -cp desktop-launcher\lib\com.sejda.desktop-launcher-1.0.0-classpath.jar,
               DesktopLauncher, args.txt])                    windowsHide, cwd=vendor
        4. on exit: read task.out (JSON result: status, failureReason, upgrade …)
        cancel = create task.kill file   (exit code 100 = cancelled)
  JVM: DesktopLauncher (Scala) -> TaskJsonParser -> sejda TaskParameters
       -> InJvmTaskExecutor / DefaultTaskExecutionService (sejda-core)
       -> task class from sejda.xml (SAMBox-based)
       -> OCR only: spawns vendor\tesseract-windows-x64\tesseract.exe (SEJDA_TESSERACT_PATH)
```

- **Framework** [seen]: Electron **42.4.0** (`version.electron`). Its own fuses [seen, REA]: RunAsNode, NODE_OPTIONS and inspect-argument fuses disabled; embedded ASAR integrity validation and OnlyLoadAppFromAsar enabled; cookie encryption enabled.
- **No local HTTP server, no port, no long-running engine** [seen]. Each task runs in a **new, short-lived JVM process**. Input and output pass through temp files (`task.in`/`task.out`); progress is logged to stdout (`Task progress: N% done`).
- **IPC** [seen in `main.js` and REA]: 10 literal channels, all for shell chores and none for PDF work: `electron.app.getPath`, `electron.app.setTitle`, `electron.app.externalLinkClicked`, `electron.app.i18n.__`, `electron.dialog.showOpenDialog|showSaveDialog|showMessageBox`, `electron.menu.popup`, `electron.menu.pageActions`, `font-scanner.getAvailableFonts`. Main also sends `before-quit` and `main.log` to renderers. The engine is reached directly from the preload's Node context (`require('child_process')`), not through ipcMain.
- **Renderer UI** [seen]: `views/*.ejs`, one page per tool, rendered through a custom `electron-ejs` file:// handler. JS is the web bundle again (`libs-and-partials.min.js`, `pages/*.min.js`, an obfuscated `pdf-editor-desktop.min.obfuscated.js`, PDF.js under `views/public/js/pdfjs`). The task JSON is the same form serialisation the web posts to `/api/tasks`.
- **Proxy support** [seen]: environment variables `SEJDA_PROXY_SERVER`, `SEJDA_PROXY_USERNAME` and `SEJDA_PROXY_PASSWORD` (the `PDFSAM_*` names also work, a hint of the shared pdfsam/Sejda lineage).
- **Enterprise configuration** [seen]: the `SEJDA_DESKTOP_INSTALLER_CONFIG` environment variable (`LICENSE_KEY=…;LOCALE=…;UPDATE_CHECK=…;DISABLED_FEATURES=…;EULA_ACCEPTED=…;AUTO_REPORT_ERRORS=…`) is copied into prefs on startup.

### 3. Component inventory

#### 3.1 Bundled runtimes and native tools [seen]

| Component | Version | Notes |
|---|---|---|
| Electron / Chromium | 42.4.0 | `LICENSE.electron` (MIT), `LICENSES.chromium.html` |
| Java runtime | **JDK 25.0.3**, a jlink image | `resources\vendor\jdk25-windows-x64`. Modules: java.base, desktop, xml, sql, naming, scripting, management, security.jgss/sasl, xml.crypto, prefs, rmi, logging, compiler, jdk.compiler, jdk.javadoc, jdk.zipfs, jdk.internal.md/opt. The vendor is not stated in the `release` file [unknown]. |
| Tesseract OCR | **4.0.0.20190314** (`libtesseract-4.dll`), MinGW build | Ships with leptonica (`liblept-5`), libtiff-5, libpng16, libjpeg-8, libwebp-7, openjp2, giflib, glib/gobject, libgomp. Only `eng.traineddata` is bundled. Other languages are downloaded on demand from `https://sejda-cdn.com/downloads/tessdata/<lang>.traineddata` into `%APPDATA%\sejda-desktop\tessdata`. |
| Ghostscript, LibreOffice, qpdf, Chromium/wkhtmltopdf for HTML→PDF, ImageMagick | **absent** | Not present anywhere in the file tree [seen]. |

#### 3.2 Java classpath (`resources\vendor\desktop-launcher\lib`, 74 jars) [seen]

**Sejda proprietary / closed:**
- `com.sejda.common-0.1-SNAPSHOT.jar` (13.7 MB, Scala): the shared "code.*" engine layer (TaskJsonParser, limits, edit, OCR, Excel, Word, deskew, flatten, etc.). It also bundles ~35 open font families (Noto, Liberation, DejaVu, Open Sans, Roboto, PT, Lato, Inter, Amiri, Carlito/Caladea, etc.).
- `com.sejda.desktop-launcher-1.0.0.jar`: `DesktopLauncher` main class, `code.limits.{DesktopPlanLimits, LicenseInformation, UntrustedLocalClock}`, `sejda.xml`, `logback.xml`. Licensed under a custom "Sejda Desktop Launcher Software Inclusion License" (Andrea Vacondio / Eduard Weissmann) in `LICENSE.txt`.
- `com.sejda.pdf2html.pdf2html-0.0.74.jar`: PDF→HTML text extraction on SAMBox (`com.sejda.pdf2html.sambox.PdfText2Html`), served from `mvn.sejda.com`.
- `org.sejda.sejda-core-pro`, `sejda-model-pro`, `sejda-sambox-pro`, `sejda-fonts-pro`: **5.1.21** ("pro" add-ons to the open Sejda SDK; parent POM `sejda-parent-pro`).

**Sejda open source (Sejda SDK / sejda.org):**
- `org.sejda.sejda-core`, `sejda-model`, `sejda-sambox`, `sejda-fonts`, `sejda-image-writers`: **5.1.23**. Their POMs point to parent `sejda-parent` and https://www.sejda.org; the license is in the parent POM, which is not shipped [unknown in artifact; upstream Sejda SDK is AGPLv3, inferred from external knowledge].
- `org.sejda.sambox` **3.0.38**: Apache-2.0 [seen in pom/LICENSE]. The NOTICE says "Based on source code originally developed in the Apache PDFBox project" (© Sober Lemur S.r.l., Sejda BV). **SAMBox, a PDFBox fork, is the PDF engine.** Apache PDFBox core itself is not shipped; only FontBox and JBIG2 are.
- `org.sejda.sejda-commons` 3.0.1, `org.sejda.sejda-io` 5.0.0.M1, `org.sejda.imageio.webp-imageio` 0.1.6 (Apache-2.0 [seen]).

**Third-party OSS:**

| Jar | Version | License (where stated in artifact) |
|---|---|---|
| Apache FontBox | 2.0.34 | Apache-2.0 [seen, Bundle-License] |
| Apache PDFBox jbig2-imageio | 3.0.4 | Apache-2.0 [inferred] |
| Apache POI / poi-ooxml / poi-ooxml-lite, XMLBeans | 5.3.0 / 5.2.1 | Apache-2.0 [inferred] |
| Bouncy Castle bcprov/bcpkix/bcutil/bcmail (jdk18on) | 1.84 | MIT-style [inferred] |
| TwelveMonkeys imageio core/jpeg/tiff/metadata + common | 3.13.1 | BSD [inferred] |
| jai-imageio-core, jai-imageio-jpeg2000 | 1.4.0 | BSD-style [inferred] |
| ICU4J | 78.3 | Unicode [inferred] |
| metadata-extractor, Adobe xmpcore | 2.19.0 / 6.1.11 | Apache / BSD [inferred] |
| Thumbnailator; image-comparison (romankh3) | 0.4.21 / 4.4.0 | MIT [inferred] |
| Guava; jsr305 | 33.2.1-jre / 3.0.2 | Apache [inferred] |
| commons-io/codec/lang3/collections4/compress/csv/math3/logging/net | 2.21.0 / 1.17.0 / 3.20.0 / 4.4 / 1.26.2 / 1.11.0 / 3.6.1 / 1.2 / 3.11.0 | Apache [inferred] |
| HttpClient/HttpCore/HttpMime | 4.5.14 / 4.4.16 | Apache [inferred] |
| jsoup | 1.18.1 | MIT [inferred] |
| Scala library, scala-xml, lift-json | 2.13.17 / 1.3.0 / 3.5.0 | Apache [inferred] |
| JNA; joda-time; paranamer; curvesapi; SparseBitSet; permit-reflect | 5.14.0 / 2.12.7 / 2.8 / 1.08 / 1.3 / 0.4 | various [inferred] |
| logback, slf4j, jcl-over-slf4j, log4j-api, jakarta.validation | 1.5.26 / 2.0.17 / 2.0.17 / 2.23.1 / 3.0.2 | EPL/LGPL, MIT, Apache [inferred] |

**Node dependencies in the asar** [seen in `package.json`]: ejs 5.0.2, electron-debug 3.2.0, font-scanner 0.2.1 (native), fs-extra 10.1.0, i18n 0.15.3, mime 3.0.0, underscore 1.13.8, username 5.1.0, htmlparser2 9.1.0, domutils 3.1.0, electron-log 5.4.4.

### 4. Task type → engine mapping

The JSON `type` values come from the `<input name="type">` fields in `views/*.ejs` [seen]. The Parameters→Task bindings come from `sejda.xml` inside `com.sejda.desktop-launcher-1.0.0.jar` [seen]. Type→Parameters links are [inferred] from class names and the constant-pool strings of `code.model.TaskJsonParser`.

| JSON `type` (desktop UI) | Parameters class | Task class (sejda.xml) |
|---|---|---|
| merge | `org.sejda.model.parameter.MergeParameters` | `org.sejda.impl.sambox.MergeTask` |
| alternateMix | `AlternateMixMultipleInputParameters` | `impl.sambox.AlternateMixTask` |
| splitByPages | `SplitByPagesParameters` / `SimpleSplitParameters` / `SplitByEveryXPagesParameters` | `impl.sambox.SplitByPageNumbersTask` |
| splitByBookmarks | `SplitByOutlineLevelParameters` (also `ExtractByOutlineParameters`) | `SplitByOutlineLevelTask` / `ExtractByOutlineTask` |
| splitBySize | `SplitBySizeParameters` | `SplitBySizeTask` |
| splitByText | `model.pro…SplitByTextContentParameters` | `impl.sambox.pro.SplitByTextContentTask` |
| splitDownTheMiddle | `SplitDownTheMiddleParameters` | `pro.SplitDownTheMiddleTask` |
| extractPages, deletePages [inferred] | `ExtractPagesParameters` | `impl.sambox.ExtractPagesTask` |
| combineReorder (organize / visually combine) | `CombineReorderParameters` | `pro.CombineReorderTask` |
| rotatePages | `RotateParameters` | `RotateTask` |
| compress | `OptimizeParameters` [inferred] | `pro.OptimizeTask` (image recompression, font subsetting, unused-resource removal: `component.optimization.*`) |
| encrypt / decrypt | `EncryptParameters` / `DecryptParameters` | `pro.EncryptTask` / `pro.DecryptTask` |
| crop | `CropParameters` | `pro.CropTask` (+ `component.crop.AutoCrop`) |
| resizePages | `ResizePagesParameters` | `pro.ResizePagesTask` |
| nup | `NupParameters` | `pro.NupTask` |
| grayscale | `ConvertToGrayscaleParameters` | `pro.ConvertToGrayscaleTask` |
| watermark | `WatermarkParameters` | `pro.WatermarkTask` |
| headerFooter, batesNumbering (page numbers) | `SetHeaderFooterParameters` | `pro.SetHeaderFooterTask` |
| repair | `RepairParameters` | `pro.RepairTask` |
| extractText | `ExtractTextParameters` | `pro.ExtractTextTask` |
| editMetadata | `SetMetadataParameters` | `SetMetadataTask` |
| jpgToPdf | `JpegToPdfParameters` | `pro.JpegToPdfTask` |
| pdfToImage (JPG/PNG/TIFF) | `PdfToJpegParameters` / `PdfToPngParameters` / `PdfToSingleTiff` / `PdfToMultipleTiff` | `PdfToMultipleImageTask` / `PdfToSingleImageTask` (SAMBox rendering) |
| edit, fillSign (editor, forms, sign) | `code.sejda.tasks.edit.EditParameters` | `code.sejda.tasks.edit.EditTask` (74 classes: text/image/shape/link/form/annotation ops) |
| pdfToDoc (PDF→Word) | `code.sejda.tasks.doc.PdfToDocParameters` | `PdfToLegibleDocTask`: pdf2html (`PdfText2Html`) → jsoup → Apache POI XWPF `.docx` [seen in strings] |
| pdfToExcelNext | `code.sejda.tasks.excel.PdfToExcelNextParameters` | `PdfToExcelNextTask`: own `TableDetector` plus sejda `DataTable` → POI `.xlsx` or `.csv` |
| ocr | `code.sejda.tasks.ocr.OcrParameters` | `OcrTask`: pages → TIFF (`PdfTiffConverter`) → external **tesseract.exe** (`OMP_THREAD_LIMIT`, PDF/text output) → `pro.component.Overlayer` merges the text layer |
| deskew | `DeskewParameters` | `code…deskew.DeskewTask` (`ImageDeskew`) |
| flatten | `FlattenParameters` | `FlattenTask` |
| extractImages | `ExtractImagesParameters` | `ExtractImagesTask` |
| renameByText | `RenameByTextParameters` | `RenameByTextTask` |
| editBookmarks | `EditBookmarksParameters` | `EditBookmarksTask` |
| deleteAnnotations | `DeleteAnnotationsParameters` | `DeleteAnnotationsTask` |
| flip | `FlipParameters` | `FlipTask` |
| (no UI) | `ViewerPreferences`, `Unpack`, `SetPagesLabel`, `SetPagesTransition` | the matching sambox tasks (registered but no page) |

**Web-only task types:** `TaskJsonParser` recognises `htmlToPdf` (`HtmlToPdfParameters`), `pdfToOfficeWord`, `pdfToOfficeExcel`, `pdfToPpt` and `docToPdf`, but **`sejda.xml` binds no task to them and the app ships no converter** (no LibreOffice, Chromium-based renderer or MS Office bridge). These "office-grade" conversions and HTML→PDF therefore run only on Sejda's servers or a third-party service; the parser is shared with the web backend. [inferred]

### 5. Licensing and limits (high level only)

- **Verify endpoint** [seen]: the renderer calls `POST https://www.sejda.com/licenses/verify` (`$.jsonPost`, `sejdaBase = "https://www.sejda.com"`) with JSON `{id: "com.sejda.sejda-desktop", version, hostname, username, hostSerial: "", licenseKey}` (built by `preload.js` `licensing.getLicenseData` and `lib/computer-id.js`). Responses such as `expired` and `access_revoked` show dedicated screens. A per-session flag `sessionStorage.licenseVerified` avoids re-verifying.
- **Stored locally** [seen]: `%APPDATA%\sejda-desktop\prefs.json` (older builds used `~/.sejda`) holds `licenseKey`, `licenseExpires`, `licenseToken`, plus UI preferences. The log is `%APPDATA%\sejda-desktop\sejda-desktop.log`.
- **Enforcement point** [seen/inferred]: each task JSON gets `key` and `token` added from prefs. Inside the JVM, `code.limits.LicenseInformation` decodes the encrypted token (it carries an expiry) and `DesktopPlanLimits` decides whether to return `upgrade` (free-tier limits such as file count, page count, image size and hourly task meters). Counters are stored on disk via `code.util.ratelimit.DiskPersistentMeter`. `UntrustedLocalClock` compares local time with internet time over NTP (commons-net) to detect clock tampering. Mechanism internals were deliberately not examined further.
- **Other outbound calls** [seen]: `GET /news/desktop?…`, the contact/bug report at `https://www.sejda.com/contact` (opt-in; it can attach the last task JSON with file passwords masked), and tessdata downloads from sejda-cdn.com.

### 6. REA Evidence IDs

| ID | What |
|---|---|
| `ev_8023f694984d3d4f018511d50ce11da057f6d45a8106a02febcf7e384e8ba517` | `inspect_electron_fuses` on `Sejda PDF Desktop.exe` |
| `ev_bb55139d2817495ebdfc66b3f12e73758e78e5d370e9ca805de15d07b7f67c4c` | `analyze_javascript_application` on `app.asar`: 943 JS files parsed; 1 BrowserWindow config, 1 contextBridge API (50 members), 10 literal IPC channels all paired. Coverage was partial: `pdf.worker.min.js` was not analysed semantically. |
| `ev_cb0b46a858b913338161fc195cdeac9483c7bbf11cc7caa40595eae3c47161f7` | Summary view of the above |

Jar, ZIP and asar facts come from direct static reads (`unzip -l`/`-p`, plus Python scripts in `agent-desktop\tools\`: `asar_x.py`, `jstr.py`, `ids.py`), not from REA Evidence.

### 7. Still unknown

- The MSI contents were not unpacked (no 7-Zip, no msiexec allowed). It is assumed identical to the portable ZIP [inferred].
- The exact JSON schema of `task.out` beyond `status`, `failureReason`, `upgrade` and the result file list.
- The algorithms inside `EditTask`, `OptimizeTask` and `TableDetector`, and the exact free-tier thresholds in `DesktopPlanLimits` (not decompiled by design).
- Upstream license of the sejda-core/model/sambox 5.1.23 jars (parent POM not shipped) and of `com.sejda.common`/pro jars (proprietary; no license file in them) [unknown].
- The JDK vendor/distribution, and the Tesseract build origin and Leptonica version.
- The server-side engine for `htmlToPdf`, `pdfToOfficeWord`, `pdfToOfficeExcel`, `pdfToPpt` and `docToPdf` (no local implementation to observe).
- Whether the Mac and Linux builds differ. `desktop-launcher.js` shows Linux uses the system Tesseract (`useEmbeddedOcr = !isLinux`) [seen].
- Runtime behaviour: nothing was executed, so heap retries, actual network calls and the progress protocol are known only from static code.

---

# Part 5: Live verification of the remaining unknowns

> Local upload, download signature, 402 body, captcha provider, server infrastructure. (source: `live-verification.md`)

Done on 2026-10-21. Traffic was that of one normal free user: one 590-byte PDF uploaded, 1 task accepted, 1 task refused at the quota, 2 status polls, 2 downloads of my own result. Nothing was done to provoke 429/430, and no signatures were forged or brute-forced.

### 1. Local file upload [observed]

Session setup is `GET /compress-pdf`. That page sets cookies `clientId` (long-lived) and `_s=60` (the backend node). It also renders `uplid` (e.g. `CR30R10211934`) and the form action `https://www.sejda.com/api/files/upload?_s=&uplid=<uplid>`.

```
POST /api/files/upload-check          (form: uplid=<uplid>)
→ 200 {"status":"ok"}

POST /api/files/upload?_s=&uplid=<uplid>
     multipart: uplid=<uplid>, file=@test.pdf (application/pdf)
     header:    X-FileLocalId: <client-chosen id>
→ 200 {"id":"10a471a3-59d5-45df-b935-bacb93ab6638-Z4MECQ35TKM30BV3_2"}
```

- **Plain PDFs are accepted:** the server takes an unzipped PDF, so the browser's zip wrapping is optional.
- **Id format:** the file id has the same shape as a URL-imported file id: `<uuid>-<16 chars>_<n>`.
- **CORS:** upload responses carry CORS for `https://www.sejda.com` with credentials, `POST` only, and `Content-Range` allowed. The allowed `Content-Range` header matches the chunked protocol.
- **Not tested:** the chunked path (`/api/files/upload-chunked`, for files over 5 MB) was not exercised live; it is known from code only.

### 2. Task → result → download [observed]

```
POST /api/tasks {"type":"compress","files":["<id>"],"uri":"/compress-pdf","failIfOutputSizeNotReduced":false,"userAgent":…,"www":"www60.sejda.com"}
→ 200 "AVKBKEXF-202610211934"    x-ratelimit-remaining: 0   x-ratelimit-wait: 2004

GET /api/tasks/AVKBKEXF-202610211934/change
→ {"status":"Completed","type":"compress","remark":"Your PDF file is already very well compressed",
   "resultFilename":"test.pdf","resultFileSize":864,
   "resultFullUrlPattern":"www.sejda.com/api/tasks/<id>/download/%7B%7Bfilename%7D%7D?s=web-<35 chars>&d=true&_s=60", …}
```

- **Telemetry is optional:** the task was accepted without `cvts`, `pdfjs`, `libsCache`, `consoleLogs` or `traceId`.
- **Task id format:** `<8 chars>-<yyyyMMddHHmm>`, i.e. a random part plus the submit time in UTC.
- **Output is rewritten:** I uploaded a PDF-1.4 file and got back PDF-1.5. This is consistent with SAMBox rewriting every output (agent 3).

### 3. Download signature `s=` [observed properties only]

- **Format:** `web-` + 35 characters of base64-like text (it can include `=`).
- **Stable:** the same value came back on repeated polls, so it is issued once per task, not per request.
- **Bearer link:** the download works with no cookies at all. The link alone grants access until the file is deleted ("after 2 hours").
- **Other parameters:**
  - `d=true` → `content-disposition: attachment`.
  - `_s=<n>` names the backend node holding the result.
  - The response also sends `cache-control: no-store, private` and `x-robots-tag: noindex…`.
- **How it is computed:** server-side, probably an HMAC or random token over task id + filename [inferred]. Not determinable from outside, and I didn't try.

### 4. Error responses

| Code | Body | How known |
|---|---|---|
| **402** | `{"reason":"tasks-per-hour","code":"tasks-per-hour"}` | **observed** |
| **430** | not observed (only appears for traffic Sejda's server flags as suspicious) | client code (below) |
| **429** | not observed (needs request flooding, which I didn't do) | client code (below) |
| **400** | plain-text validation message | client code (agent 2) |

**402 details:** headers `x-ratelimit-remaining: -1` and `x-ratelimit-wait: 1956` (seconds until the window resets). `x-sejda-bf: safe` appeared on this response; it may be a bot/fraud-check verdict [inferred].

**430 / 429 client behaviour:**
- **430:** the client only looks at the status code and opens the captcha (§5).
- **429:** the client ignores the body and shows "Too many attempts. Please try again later".
- **400:** the client shows the response text.

**Quota scope:** the free quota of 3 tasks per hour is counted **per IP/network, not per cookie**. My fresh session (new `clientId`) started at the count left by agent 1's earlier tasks.

### 5. Captcha [observed]

The captcha is **Cloudflare Turnstile**, loaded from `challenges.cloudflare.com/turnstile/v0/api.js?render=explicit`. The flow:
1. The server returns 430 for a task submission.
2. The client opens an iframe at `/captcha`.
3. That page calls `turnstile.render('#cf-turnstile', {action:'taskSubmit', sitekey:…})`.
4. On success it calls `window.top.captchaCallback(token)`.
5. The original task body is resubmitted with `captchaToken` added.

The token is reset after 290 s, because it expires at 300 s. Errors are tracked as `turnstileClientError`.

### 6. Server internals (public signals only)

**Edge [observed]:**
- **Cloudflare in front of everything:** `server: cloudflare`, `cf-ray` (the observed request was served from the DEL PoP), HTTP/3, and NEL reporting.
- **DNS:** `www.sejda.com`, `a.sejda.com` (analytics), `downloads.sejda-cdn.com` and `sejda-cdn.com` all resolve to Cloudflare addresses.

**Backend nodes [observed + inferred]:**
- **Numbered nodes:** the backend is a pool of nodes named `www<N>.sejda.com`; I saw `www23`, `www43` and `www60`. These names have **no public DNS**, so they are internal origin names behind Cloudflare.
- **Sticky sessions [inferred]:** the `_s=<N>` cookie and the `_s` query parameter pin a browser to one node. Uploaded files and results probably live on that node's local storage, which is why the download URL carries `_s` and the task body carries `www`.

**Application layer [inferred]:**
- **Java:** the HttpOnly `JSESSIONID` cookie (agent 1) means a Java servlet container. Agent 3 found the engine is Java + Scala (SAMBox + Sejda SDK + pro modules), so the web backend most likely runs the same engine in-process or as workers.
- **HTML→PDF and Office-grade conversions:** these have no engine in Desktop, so they need extra server-side services. A headless browser for HTML→PDF is the likely candidate [inferred, not confirmed].

**Not knowable from outside:** queue design, node count, storage and cleanup jobs, and the exact HTML→PDF / Office conversion engines.

---

# Part 6: Full tool catalog (every option of every page)

> Extracted from the saved HTML of all 49 pages (source: `sejda-tools-catalog.json`).
- **Excluded fields:** the shared support-form and housekeeping fields (`uplid`, `file`, `filePwd`, `email`, `message`, `suflet`, …).
- **Defaults:** "Values seen" lists the values present in the markup (radio/select options or defaults). Unset options are usually omitted from the request, so the server applies its own defaults.
- **Not real options:** the `key/AWSAccessKeyId/acl/policy/signature/x-amz-*` fields on some pages are empty S3 form remnants. `thumbsSize` and `mode` (page/file) are thumbnail-UI controls.

### alternate-mix-pdf

- **URL:** https://www.sejda.com/alternate-mix-pdf
- **Title:** Alternate &amp; Mix Odd and Even PDF Pages
- **Description:** Alternate & Mix Odd and Even PDF Pages. Mixes pages from 2 or more documents, alternating between them. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `alternateMix`
- **Submitted `type`:** `alternateMix`
- **Accepted files:** pdf ; pdf,png,gif,jpg,jpeg,tif,tiff,bmp,webp

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `key` | hidden | (free input) |
| `AWSAccessKeyId` | hidden | (free input) |
| `acl` | hidden | (free input) |
| `success_action_redirect` | hidden | (free input) |
| `policy` | hidden | (free input) |
| `signature` | hidden | (free input) |
| `Content-type` | hidden | (free input) |
| `x-amz-storage-class` | hidden | (free input) |
| `reverse` | radio | `false`, `true` |
| `step[]` | text | `1` |
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |

### bates-numbering-pdf

- **URL:** https://www.sejda.com/bates-numbering-pdf
- **Title:** Bates numbering of PDF files
- **Description:** Bates numbering of PDF files. Bates stamp multiple files at once. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `batesNumbering`
- **Submitted `type`:** `batesNumbering`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `pattern` | hidden | `Exhibit [FILE_NUMBER] - Case XYZ - [BATES_NUMBER]` |
| `batesDigits` | hidden | `6` |
| `bates-with-exhibit-and-page_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-and-page_case` | text | `Case XYZ` |
| `bates-with-exhibit-and-page_page` | text | `Page` |
| `bates-with-exhibit-5-digits-and-page_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-5-digits-and-page_case` | text | `Case XYZ` |
| `bates-with-exhibit-5-digits-and-page_page` | text | `Page` |
| `bates-with-exhibit-4-digits-and-page_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-4-digits-and-page_case` | text | `Case XYZ` |
| `bates-with-exhibit-4-digits-and-page_page` | text | `Page` |
| `bates-with-exhibit-3-digits-and-page_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-3-digits-and-page_case` | text | `Case XYZ` |
| `bates-with-exhibit-3-digits-and-page_page` | text | `Page` |
| `bates-with-exhibit-1-digits-and-page_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-1-digits-and-page_case` | text | `Case XYZ` |
| `bates-with-exhibit-1-digits-and-page_page` | text | `Page` |
| `bates-with-exhibit_exhibit` | text | `Exhibit` |
| `bates-with-exhibit_case` | text | `Case XYZ` |
| `full-bates_case` | text | `Case XYZ` |
| `bates-with-exhibit-5-digits_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-5-digits_case` | text | `Case XYZ` |
| `bates-with-exhibit-4-digits_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-4-digits_case` | text | `Case XYZ` |
| `bates-with-exhibit-3-digits_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-3-digits_case` | text | `Case XYZ` |
| `bates-with-exhibit-1-digits_exhibit` | text | `Exhibit` |
| `bates-with-exhibit-1-digits_case` | text | `Case XYZ` |
| `full-bates-5-digits_case` | text | `Case XYZ` |
| `full-bates-4-digits_case` | text | `Case XYZ` |
| `full-bates-3-digits_case` | text | `Case XYZ` |
| `full-bates-1-digits_case` | text | `Case XYZ` |
| `bates-custom_text` | text | `Exhibit [FILE_NUMBER] Case XYZ [BATES_NUMBER]` |
| `batesStartFrom` | text | `1` |
| `batesIncrement` | hidden | `1` |
| `fileCountStartFrom` | text | `1` |
| `addMargins` | radio | `false`, `true` |
| `font` | radio | `times_roman`, `helvetica`, `courier` |
| `color` | hidden | `#000000` |
| `style` | select | `bates-with-exhibit-and-page`, `bates-with-exhibit`, `full-bates`, `bates-with-exhibit-5-digits-and-page`, `bates-with-exhibit-5-digits`, `full-bates-5-digits`, `bates-with-exhibit-4-digits-and-page`, `bates-with-exhibit-4-digits`, `full-bates-4-digits`, `bates-with-exhibit-3-digits-and-page`, `bates-with-exhibit-3-digits`, `full-bates-3-digits`, `bates-with-exhibit-1-digits-and-page`, `bates-with-exhibit-1-digits`, `full-bates-1-digits`, `just-number`, `just-number-5-digits`, `just-number-4-digits`, `just-number-3-digits`, `just-number-1-digits`, `bates-custom` |
| `pageLocation` | select | `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right` |
| `fontSize` | select | `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `18`, `20`, `22`, `24`, `26`, `28`, `30`, `45`, `60` |

### compress-pdf

- **URL:** https://www.sejda.com/compress-pdf
- **Title:** Compress PDF online
- **Description:** Compress PDF. Reduce the size of your PDF. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `compress`
- **Submitted `type`:** `compress`
- **Accepted files:** pdf
- **Free file-size limit:** 100 MB

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `imageQuality` | radio | `0.65`, `0.8`, `1` |
| `imageDpi` | radio | `72`, `100`, `144`, `200`, `300`, `720` |
| `imageConversion` | radio | `none`, `grayscale` |
| `discardMultimedia` | radio | `all`, `none` |
| `subsetFonts` | radio | `false`, `true` |

### crop-pdf

- **URL:** https://www.sejda.com/crop-pdf
- **Title:** Crop PDF Online. Automatically trim white margins in one click.
- **Description:** Automatically crop white margins or preview PDF pages and select crop areas. No registration or watermarks.
- **Task type (data-task):** `crop`
- **Submitted `type`:** `crop`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `all`, `individual`, `odd-even` |
| `marginTop` | text | `0.0` |
| `areaWidth` | text | `0.0` |
| `areaHeight` | text | `0.0` |
| `unit` | radio | `inch`, `cm` |
| `marginBottom` | text | `0.0` |
| `marginLeft` | text | `0.0` |
| `marginRight` | text | `0.0` |
| `autoCropMode` | hidden | `none` |

### delete-pdf-annotations

- **URL:** https://www.sejda.com/delete-pdf-annotations
- **Title:** Delete PDF annotations Online
- **Description:** Delete PDF annotations. Batch remove highlights, strikeouts or any other annotations from a PDF document. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `deleteAnnotations`
- **Submitted `type`:** `deleteAnnotations`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `annotationTypes[]` | checkbox | `all`, `highlight`, `strikeout`, `underline`, `ink`, `polygon`, `square`, `circle`, `line`, `polyline`, `link`, `text`, `freetext`, `popup` |
| `pages` | text | (free input) |

### delete-pdf-pages

- **URL:** https://www.sejda.com/delete-pdf-pages
- **Title:** Delete pages from your PDF online
- **Description:** Easily remove pages from a PDF. No registration or watermarks. Zoom pages. Specify an interval when deleting many pages. Batch process multiple files at once.
- **Task type (data-task):** `deletePages`
- **Submitted `type`:** `deletePages`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `pages` | text | (free input) |
| `discardOutline` | checkbox | `true` |

### deskew-pdf

- **URL:** https://www.sejda.com/deskew-pdf
- **Title:** Deskew PDF Online
- **Description:** Automatically straighten and de-skew any scanned PDF. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `deskew`
- **Submitted `type`:** `deskew`
- **Accepted files:** pdf
- **Free file-size limit:** 100 MB

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `angles` | hidden | (free input) |
| `mode` | hidden | `automatic` |
| `pages` | text | (free input) |
| `onlyStronglySkewed` | checkbox | `true` |

### desktop

- **URL:** https://www.sejda.com/desktop
- **Title:** Sejda PDF Desktop - Official Website
- **Task type (data-task):** none (not a task page)

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `csrf` | hidden | (per-page token, omitted) |
| `password` | password | (free input) |
| `emailVerificationCode` | text | (free input) |
| `agreeTerms` | checkbox | `yes` |
| `seats` | hidden | `1` |
| `discount` | hidden | `0` |
| `stripePublicKey` | hidden | (free input) |
| `paypalEnv` | hidden | (free input) |
| `firstName` | text | (free input) |
| `lastName` | text | (free input) |
| `companyName` | text | (free input) |
| `vatNumber` | text | (free input) |
| `billingAddressCountry` | select | `FR`, `CA`, `BR`, `IN`, `ES`, `US`, `GB`, `AF`, `AX`, `AL`, `DZ`, `AS`, `AD`, `AO`, `AI`, `AQ`, `AG`, `AR`, `AM`, `AW`, `AU`, `AT`, `AZ`, `BS`, `BH`, `BD`, `BB`, `BY`, `BE`, `BZ`, `BJ`, `BM`, `BT`, `BO`, `BQ`, `BA`, `BW`, `BV`, `IO`, `VG`, `BN`, `BG`, `BF`, `BI`, `KH`, `CM`, `IC`, `CV`, `KY`, `CF`, `TD`, `CL`, `CN`, `CX`, `CC`, `CO`, `KM`, `CD`, `CG`, `CK`, `CR`, `HR`, `CU`, `CW`, `CY`, `CZ`, `DK`, `DJ`, `DM`, `DO`, `EC`, `EG`, `SV`, `GQ`, `ER`, `EE`, `ET`, `FK`, `FO`, `FJ`, `FI`, `GF`, `PF`, `TF`, `GA`, `GM`, `GE`, `DE`, `GH`, `GI`, `GR`, `GL`, `GD`, `GP`, `GU`, `GT`, `GG`, `GN`, `GW`, `GY`, `HT`, `HM`, `HN`, `HK`, `HU`, `IS`, `ID`, `IR`, `IQ`, `IE`, `IM`, `IL`, `IT`, `CI`, `JM`, `JP`, `JE`, `JO`, `KZ`, `KE`, `KI`, `KP`, `KR`, `XK`, `KW`, `KG`, `LA`, `LV`, `LB`, `LS`, `LR`, `LY`, `LI`, `LT`, `LU`, `MO`, `MK`, `MG`, `MW`, `MY`, `MV`, `ML`, `MT`, `MH`, `MQ`, `MR`, `MU`, `YT`, `MX`, `FM`, `MD`, `MC`, `MN`, `ME`, `MS`, `MA`, `MZ`, `MM`, `NA`, `NR`, `NP`, `NL`, `NC`, `NZ`, `NI`, `NE`, `NG`, `NU`, `NF`, `MP`, `NO`, `OM`, `PK`, `PW`, `PS`, `PA`, `PG`, `PY`, `PE`, `PH`, `PN`, `PL`, `PT`, `PR`, `QA`, `RE`, `RO`, `RU`, `RW`, `BL`, `SH`, `KN`, `LC`, `MF`, `PM`, `VC`, `WS`, `SM`, `ST`, `SA`, `SN`, `RS`, `SC`, `SL`, `SG`, `SX`, `SK`, `SI`, `SB`, `SO`, `ZA`, `GS`, `SS`, `LK`, `SD`, `SR`, `SJ`, `SZ`, `SE`, `CH`, `SY`, `TW`, `TJ`, `TZ`, `TH`, `TL`, `TG`, `TK`, `TO`, `TT`, `TN`, `TR`, `TM`, `TC`, `TV`, `UG`, `UA`, `AE`, `UM`, `VI`, `UY`, `UZ`, `VU`, `VA`, `VE`, `VN`, `WF`, `EH`, `YE`, `ZM`, `ZW` |

### developers

- **URL:** https://www.sejda.com/developers
- **Title:** Developers - API Docs
- **Description:** Developer documentation for our HTML to PDF API, web integrations such as 'Save as PDF' links and deep links to open your files with SEJDA.COM tools.
- **Task type (data-task):** none (not a task page)

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `fileLocation` | radio | `website`, `gdrive`, `dropbox`, `computer`, `other` |
| `selectedTool` | radio | `sign-pdf`, `pdf-editor` |
| `returnEmail` | email | (free input) |

### edit-pdf-metadata

- **URL:** https://www.sejda.com/edit-pdf-metadata
- **Title:** Edit PDF metadata online
- **Description:** Easily change PDF metadata such as Author, Title, Subject, Keywords and other fields. Free, no registration or watermarks.
- **Task type (data-task):** `editMetadata`
- **Submitted `type`:** `editMetadata`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `removeAllMetadata` | hidden | `false` |
| `metadata.Title` | text | (free input) |

### encrypt-pdf

- **URL:** https://www.sejda.com/encrypt-pdf
- **Title:** Password Protect PDF - Safely Encrypt your PDF Online
- **Description:** No registration or watermarks. Simple and secure way to password protect your PDFs with strong AES 256 bits encryption.
- **Task type (data-task):** `encrypt`
- **Submitted `type`:** `encrypt`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `userPassword` | text | (free input) |
| `ownerPassword` | text | (free input) |
| `encryptionAlgorithm` | radio | `rc4_128`, `aes_128`, `aes_256` |
| `permissions[]` | checkbox | `modify`, `copy`, `degradedprinting`, `print`, `fill`, `modifyannotations`, `assemble` |

### extract-images-from-pdf

- **URL:** https://www.sejda.com/extract-images-from-pdf
- **Title:** Extract images from PDF
- **Description:** Extract images from PDF. Save each image from the PDF as a separate file. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `extractImages`
- **Submitted `type`:** `extractImages`
- **Accepted files:** pdf
- **Options:** none (file only)

### extract-pdf-pages

- **URL:** https://www.sejda.com/extract-pdf-pages
- **Title:** Extract pages from PDF online
- **Description:** Extract PDF Pages. Get a new document containing only the desired pages. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `extractPages`
- **Submitted `type`:** `extractPages`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `pages` | radio | `odd`, `even`, `none` |
| `discardOutline` | checkbox | `true` |

### extract-text-from-pdf

- **URL:** https://www.sejda.com/extract-text-from-pdf
- **Title:** PDF to Text
- **Description:** Extract text from PDF. Copies all text from the PDF document and extracts it to a separate text file. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `extractText`
- **Submitted `type`:** `extractText`
- **Accepted files:** pdf
- **Options:** none (file only)

### flatten-pdf

- **URL:** https://www.sejda.com/flatten-pdf
- **Title:** Flatten PDF Online
- **Description:** Print & scan in one step. Converts PDF pages to images so text can&#x2019;t be copied or modified directly. Makes fillable PDFs read-only. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `flatten`
- **Submitted `type`:** `flatten`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `flattenMode` | radio | `all`, `onlyforms` |
| `resolution` | radio | `75`, `100`, `150`, `220` |

### flip-pdf

- **URL:** https://www.sejda.com/flip-pdf
- **Title:** Flip PDF Online - Mirror Pages Horizontally or Vertically
- **Description:** Flip a PDF online for free. Mirror pages horizontally or vertically. Iron-on transfers, fix reversed scans, backwards PDF text, PDF content upside down or reversed. No install, no signup. It's free, quick and easy to use.
- **Task type (data-task):** `flip`
- **Submitted `type`:** `flip`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `flipMode` | radio | `horizontal`, `vertical` |

### grayscale-pdf

- **URL:** https://www.sejda.com/grayscale-pdf
- **Title:** Convert PDF to Grayscale online
- **Description:** Convert PDF to Grayscale. Make a PDF text and images grayscale. Black and white printing. Export PDF for offset printing. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `grayscale`
- **Submitted `type`:** `grayscale`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `textConversion` | radio | `grayscale`, `black` |
| `imageConversion` | radio | `grayscale`, `none` |
| `compressImages` | checkbox | `true` |

### header-footer-pdf

- **URL:** https://www.sejda.com/header-footer-pdf
- **Title:** Add Header and Footer to PDF files online
- **Description:** Add PDF Header & Footer. Apply page numbers or text labels to PDF files. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `headerFooter`
- **Submitted `type`:** `headerFooter`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `pattern` | hidden | (free input) |
| `hf-format-customize[]` | text | `Page`, `[PAGE_ARABIC]`, `[PAGE_ROMAN]`, `of`, `[TOTAL_PAGES_ARABIC]`, `[BASE_NAME]`, `Draft version` |
| `font` | radio | `times_roman`, `helvetica`, `courier` |
| `color` | hidden | `#000000` |
| `addMargins` | radio | `false`, `true` |
| `pages` | text | (free input) |
| `pageCountStartFrom` | text | (free input) |
| `pageLocation` | select | `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right` |
| `fontSize` | select | `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `18`, `20`, `22`, `24`, `26`, `28` |

### help

- **URL:** https://www.sejda.com/help
- **Title:** Help
- **Task type (data-task):** none (not a task page)
- **Options:** none (file only)

### html-pdf-api

- **URL:** https://www.sejda.com/html-pdf-api
- **Title:** HTML to PDF API
- **Task type (data-task):** none (not a task page)

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `csrf` | hidden | (per-page token, omitted) |
| `password` | password | (free input) |
| `emailVerificationCode` | text | (free input) |
| `agreeTerms` | checkbox | `yes` |
| `seats` | hidden | `1` |
| `discount` | hidden | `0` |
| `stripePublicKey` | hidden | (free input) |
| `paypalEnv` | hidden | (free input) |
| `firstName` | text | (free input) |
| `lastName` | text | (free input) |
| `companyName` | text | (free input) |
| `vatNumber` | text | (free input) |
| `billingAddressCountry` | select | `FR`, `CA`, `BR`, `IN`, `ES`, `US`, `GB`, `AF`, `AX`, `AL`, `DZ`, `AS`, `AD`, `AO`, `AI`, `AQ`, `AG`, `AR`, `AM`, `AW`, `AU`, `AT`, `AZ`, `BS`, `BH`, `BD`, `BB`, `BY`, `BE`, `BZ`, `BJ`, `BM`, `BT`, `BO`, `BQ`, `BA`, `BW`, `BV`, `IO`, `VG`, `BN`, `BG`, `BF`, `BI`, `KH`, `CM`, `IC`, `CV`, `KY`, `CF`, `TD`, `CL`, `CN`, `CX`, `CC`, `CO`, `KM`, `CD`, `CG`, `CK`, `CR`, `HR`, `CU`, `CW`, `CY`, `CZ`, `DK`, `DJ`, `DM`, `DO`, `EC`, `EG`, `SV`, `GQ`, `ER`, `EE`, `ET`, `FK`, `FO`, `FJ`, `FI`, `GF`, `PF`, `TF`, `GA`, `GM`, `GE`, `DE`, `GH`, `GI`, `GR`, `GL`, `GD`, `GP`, `GU`, `GT`, `GG`, `GN`, `GW`, `GY`, `HT`, `HM`, `HN`, `HK`, `HU`, `IS`, `ID`, `IR`, `IQ`, `IE`, `IM`, `IL`, `IT`, `CI`, `JM`, `JP`, `JE`, `JO`, `KZ`, `KE`, `KI`, `KP`, `KR`, `XK`, `KW`, `KG`, `LA`, `LV`, `LB`, `LS`, `LR`, `LY`, `LI`, `LT`, `LU`, `MO`, `MK`, `MG`, `MW`, `MY`, `MV`, `ML`, `MT`, `MH`, `MQ`, `MR`, `MU`, `YT`, `MX`, `FM`, `MD`, `MC`, `MN`, `ME`, `MS`, `MA`, `MZ`, `MM`, `NA`, `NR`, `NP`, `NL`, `NC`, `NZ`, `NI`, `NE`, `NG`, `NU`, `NF`, `MP`, `NO`, `OM`, `PK`, `PW`, `PS`, `PA`, `PG`, `PY`, `PE`, `PH`, `PN`, `PL`, `PT`, `PR`, `QA`, `RE`, `RO`, `RU`, `RW`, `BL`, `SH`, `KN`, `LC`, `MF`, `PM`, `VC`, `WS`, `SM`, `ST`, `SA`, `SN`, `RS`, `SC`, `SL`, `SG`, `SX`, `SK`, `SI`, `SB`, `SO`, `ZA`, `GS`, `SS`, `LK`, `SD`, `SR`, `SJ`, `SZ`, `SE`, `CH`, `SY`, `TW`, `TJ`, `TZ`, `TH`, `TL`, `TG`, `TK`, `TO`, `TT`, `TN`, `TR`, `TM`, `TC`, `TV`, `UG`, `UA`, `AE`, `UM`, `VI`, `UY`, `UZ`, `VU`, `VA`, `VE`, `VN`, `WF`, `EH`, `YE`, `ZM`, `ZW` |

### html-to-pdf

- **URL:** https://www.sejda.com/html-to-pdf
- **Title:** Convert HTML to PDF Online
- **Description:** HTML to PDF. Convert HTML pages to a PDF document. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `htmlToPdf`
- **Submitted `type`:** `htmlToPdf`
- **Accepted files:** html
- **Free file-size limit:** 30 MB

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `save-link` | hidden | `false` |
| `partialContentAllowed` | hidden | `true` |
| `blockAds` | hidden | `true` |
| `timezone` | hidden | (free input) |
| `fromBookmarklet` | hidden | `false` |
| `viewportWidth` | number | (free input) |
| `pageMargin` | number | `0` |
| `hideNotices` | checkbox | `true` |
| `usePrintMedia` | checkbox | `true` |
| `includeHeaderFooterDetails` | checkbox | `true` |
| `pageSize` | select | `A4`, `A3`, `A2`, `Letter`, `Legal` |
| `pageOrientation` | select | `auto`, `portrait`, `landscape` |
| `pageMarginUnits` | select | `px`, `in`, `cm`, `mm` |
| `delay` | select | `0`, `1`, `2`, `3`, `4`, `5` |
| `browserLocation` | select | `us`, `eu` |
| `lang` | select | `ar`, `am`, `bg`, `bn`, `ca`, `cs`, `da`, `de`, `el`, `en`, `en_AU`, `en_GB`, `en_US`, `es`, `es_419`, `et`, `fa`, `fi`, `fil`, `fr`, `gu`, `he`, `hi`, `hr`, `hu`, `id`, `it`, `ja`, `kn`, `ko`, `lt`, `lv`, `ml`, `mr`, `ms`, `nl`, `no`, `pl`, `pt_BR`, `pt_PT`, `ro`, `ru`, `sk`, `sl`, `sr`, `sv`, `sw`, `ta`, `te`, `th`, `tr`, `uk`, `vi`, `zh_CN`, `zh_TW` |
| `urls` | textarea | (free input) |

### jpg-to-pdf

- **URL:** https://www.sejda.com/jpg-to-pdf
- **Title:** JPG to PDF Online
- **Description:** JPG to PDF. Convert Images to PDF. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `jpgToPdf`
- **Submitted `type`:** `jpgToPdf`
- **Accepted files:** png,gif,jpg,jpeg,tif,tiff,bmp,webp ; pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `thumbsSize` | range | `150` |
| `mergeOutputs` | checkbox | `true` |
| `pageSizeWidth` | number | `0.000` |
| `pageSizeHeight` | number | `0.000` |
| `pageSize` | select | `auto`, `custom`, `A5`, `A4`, `A3`, `A2`, `A1`, `letter`, `legal`, `legder`, `tabloid`, `executive` |
| `pageOrientation` | select | `auto`, `portrait`, `landscape` |
| `pageMargin` | select | `0` |

### merge-pdf

- **URL:** https://www.sejda.com/merge-pdf
- **Title:** Merge PDF Files Online
- **Description:** Merge PDF Files Online. Combine multiple PDFs and images into one. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `merge`
- **Submitted `type`:** `merge`
- **Accepted files:** pdf,png,gif,jpg,jpeg,tif,tiff,bmp,webp ; pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `outputFilename` | hidden | (free input) |
| `blankPageIfOdd` | checkbox | `true` |
| `normalizePageSizes` | checkbox | `true` |
| `firstInputCoverTitle` | checkbox | `true` |
| `filenameFooter` | checkbox | `true` |
| `outlinePolicy` | radio | `retain`, `discard`, `one_entry_each_doc`, `retain_as_one_entry` |
| `tocPolicy` | radio | `none`, `file_names`, `doc_titles` |
| `acroFormPolicy` | radio | `none`, `merge`, `merge_renaming`, `flatten` |

### n-up-pdf

- **URL:** https://www.sejda.com/n-up-pdf
- **Title:** N-up &amp; PDF Imposition
- **Description:** Print multiple pages per sheet per paper. A5 plan as 4-up on A3 or A4 2-up on A3. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `nup`
- **Submitted `type`:** `nup`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `n` | radio | `2`, `4`, `8`, `16`, `32` |
| `pageOrdering` | radio | `horizontal`, `vertical` |
| `preservePageSize` | checkbox | `true` |
| `rightToLeft` | checkbox | `true` |

### ocr-pdf

- **URL:** https://www.sejda.com/ocr-pdf
- **Title:** OCR Recognize Text in PDF Online
- **Description:** Convert PDF scans to searchable text and PDFs. Extract text from scans. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `ocr`
- **Submitted `type`:** `ocr`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `outputFormats[]` | checkbox | `pdf`, `txt` |
| `lang` | select | (free input) |

### organize-pdf

- **URL:** https://www.sejda.com/organize-pdf
- **Title:** Organize PDF Pages Online
- **Description:** Organize PDF Pages. Arrange and reorder PDF pages. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `combineReorder`
- **Submitted `type`:** `combineReorder`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `outputFilename` | hidden | (free input) |

### page-numbers-pdf

- **URL:** https://www.sejda.com/page-numbers-pdf
- **Title:** Add PDF Page Numbers
- **Description:** Apply page numbers to PDF pages. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `headerFooter`
- **Submitted `type`:** `headerFooter`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `pattern` | hidden | (free input) |
| `hf-format-customize[]` | text | `Page`, `[PAGE_ARABIC]`, `[PAGE_ROMAN]`, `of`, `[TOTAL_PAGES_ARABIC]`, `[BASE_NAME]`, `Draft version` |
| `font` | radio | `times_roman`, `helvetica`, `courier` |
| `color` | hidden | `#000000` |
| `addMargins` | radio | `false`, `true` |
| `pages` | text | (free input) |
| `pageCountStartFrom` | text | (free input) |
| `pageLocation` | select | `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right` |
| `fontSize` | select | `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `18`, `20`, `22`, `24`, `26`, `28` |

### pdf-bookmarks

- **URL:** https://www.sejda.com/pdf-bookmarks
- **Title:** Create PDF Bookmarks
- **Description:** Create PDF Bookmarks. Add, modify and remove bookmarks from PDF document outline. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `editBookmarks`
- **Submitted `type`:** `editBookmarks`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `jsonData` | hidden | (free input) |
| `current_page_input` | text | `1` |
| `search_input` | text | (free input) |
| `bookmarkTitle` | text | (free input) |
| `bookmarkPage` | text | (free input) |
| `bookmarkParent` | select | (free input) |

### pdf-editor

- **URL:** https://www.sejda.com/pdf-editor
- **Title:** Easy to use Online PDF editor
- **Description:** Free, no watermarks or registration. Edit PDF files for free. Fill & sign PDFs. Change existing text and links. Find & replace text. Whiteout. Add text, images, links and annotations.
- **Task type (data-task):** `edit`
- **Submitted `type`:** `edit`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `fontSize2` | number | `10` |
| `kind` | radio | `uri`, `mailto`, `tel`, `page` |
| `targetURL` | text | (free input) |
| `targetEmailAddress` | text | (free input) |
| `targetTel` | text | (free input) |
| `targetPage` | text | (free input) |
| `fieldName` | text | (free input) |
| `fieldValue` | text | (free input) |
| `fieldMultiselect` | checkbox | (free input) |
| `fieldComb` | checkbox | (free input) |
| `fieldCombOfCharsLength` | text | `8` |
| `fieldHasMaxLength` | checkbox | (free input) |
| `fieldCharsMaxLength` | text | `20` |
| `fieldRequired` | checkbox | (free input) |
| `noautocomplete` | text | `Default value2` |
| `imageRepeatOnAllPagesCheck` | checkbox | (free input) |
| `elapsedTime` | hidden | (free input) |
| `recovered` | hidden | `false` |
| `fontOption` | radio | (free input) |
| `findText` | text | (free input) |
| `replaceText` | text | (free input) |
| `replaceMatchCase` | checkbox | (free input) |
| `replaceMatchLinks` | checkbox | (free input) |
| `hexcolor` | text | `#FF0000` |
| `color` | text | `#FF0000` |
| `saveSignature` | checkbox | (free input) |
| `stampDateStyle` | select | `none`, `date`, `date-time`, `date-dm`, `date-time-dm` |
| `fieldOptions` | textarea | (free input) |

### pdf-forms

- **URL:** https://www.sejda.com/pdf-forms
- **Title:** Create Fillable PDF Online
- **Description:** Make PDF Fillable. Online, free, no watermarks or registration. Add interactive form fields to existing PDF.
- **Task type (data-task):** `edit`
- **Submitted `type`:** `edit`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `fontSize2` | number | `10` |
| `fieldName` | text | (free input) |
| `fieldValue` | text | (free input) |
| `fieldMultiselect` | checkbox | (free input) |
| `fieldComb` | checkbox | (free input) |
| `fieldCombOfCharsLength` | text | `8` |
| `fieldHasMaxLength` | checkbox | (free input) |
| `fieldCharsMaxLength` | text | `20` |
| `fieldRequired` | checkbox | (free input) |
| `noautocomplete` | text | `Default value2` |
| `elapsedTime` | hidden | (free input) |
| `recovered` | hidden | `false` |
| `fontOption` | radio | (free input) |
| `findText` | text | (free input) |
| `replaceText` | text | (free input) |
| `replaceMatchCase` | checkbox | (free input) |
| `replaceMatchLinks` | checkbox | (free input) |
| `hexcolor` | text | `#FF0000` |
| `color` | text | `#FF0000` |
| `saveSignature` | checkbox | (free input) |
| `stampDateStyle` | select | `none`, `date`, `date-time`, `date-dm`, `date-time-dm` |
| `fieldOptions` | textarea | (free input) |

### pdf-to-excel

- **URL:** https://www.sejda.com/pdf-to-excel
- **Title:** PDF to Excel or CSV
- **Description:** PDF to Excel or CSV. Convert PDF to Excel or CSV online for free. Extract table data from PDF. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `pdfToExcelNext`
- **Submitted `type`:** `pdfToExcelNext`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `exportFormat` | hidden | `excel` |
| `singleSheet` | checkbox | `true` |

### pdf-to-jpg

- **URL:** https://www.sejda.com/pdf-to-jpg
- **Title:** Convert PDF to Images Online. PDF to JPG. PDF to PNG. PDF to TIFF
- **Description:** Free, no watermarks or registration. Batch convert multiple files. Easy way to convert PDF doc to images.
- **Task type (data-task):** `pdfToImage`
- **Submitted `type`:** `pdfToImage`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `pages` | hidden | (free input) |
| `allPages` | hidden | (free input) |
| `resolution` | radio | `75`, `150`, `220` |
| `imageFormat` | radio | `jpg`, `png`, `tiff` |
| `tiffSingleFileWithAllPages` | checkbox | `true` |
| `imageColorType` | radio | `rgb`, `grayscale`, `black_white` |

### pdf-to-ppt

- **URL:** https://www.sejda.com/pdf-to-ppt
- **Title:** Convert PDF to PowerPoint online
- **Description:** High fidelity. Free online conversion from PPT to PDF
- **Task type (data-task):** `pdfToPpt`
- **Submitted `type`:** `pdfToPpt`
- **Accepted files:** pdf
- **Options:** none (file only)

### pdf-to-word

- **URL:** https://www.sejda.com/pdf-to-word
- **Title:** Convert PDF to Word DOC online
- **Description:** Free conversion from PDF to DOC online.
- **Task type (data-task):** `pdfToDoc`
- **Submitted `type`:** `pdfToOfficeWord`
- **Accepted files:** pdf
- **Options:** none (file only)

### rename-pdf

- **URL:** https://www.sejda.com/rename-pdf
- **Title:** Rename PDF By Text Content
- **Description:** Rename PDF By Text Content. Change document filename based on text from the PDF pages. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `renameByText`
- **Submitted `type`:** `renameByText`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `areas` | hidden | `[]` |
| `renamePattern` | text | (free input) |

### repair-pdf

- **URL:** https://www.sejda.com/repair-pdf
- **Title:** Repair PDF Online
- **Description:** Repair PDF. Recover data from a corrupted or damaged PDF document. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `repair`
- **Submitted `type`:** `repair`
- **Accepted files:** pdf
- **Options:** none (file only)

### resize-pdf

- **URL:** https://www.sejda.com/resize-pdf
- **Title:** Resize PDF Online
- **Description:** Add page margins and padding, Change PDF page size. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `resizePages`
- **Submitted `type`:** `resizePages`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `pages` | hidden | (free input) |
| `pageSize` | hidden | `custom`, `a1`, `a2`, `a3`, `a4`, `a5`, `a6`, `letter`, `legal`, `ledger`, `tabloid`, `executive` |
| `marginTop` | number | `0.0` |
| `marginLeft` | number | `0.0` |
| `marginRight` | number | `0.0` |
| `unit` | radio | `inch`, `cm` |
| `marginBottom` | number | `0.0` |
| `pageSizeWidth` | number | `0.000` |
| `pageSizeHeight` | number | `0.000` |

### rotate-pdf-pages

- **URL:** https://www.sejda.com/rotate-pdf-pages
- **Title:** Rotate PDF - Rotate Pages, Online, for Free
- **Description:** Rotate and save PDF pages permanently. Online, free.
- **Task type (data-task):** `rotatePages`
- **Submitted `type`:** `rotatePages`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |

### sign-pdf

- **URL:** https://www.sejda.com/sign-pdf
- **Title:** Easy Fill &amp; Sign PDF Online
- **Description:** Free, no watermarks or registration. Fill & Sign PDF files for free. Fill out PDF forms. Add signature to PDF.
- **Task type (data-task):** `fillSign`
- **Submitted `type`:** `fillSign`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `fontSize2` | number | `10` |
| `imageRepeatOnAllPagesCheck` | checkbox | (free input) |
| `elapsedTime` | hidden | (free input) |
| `recovered` | hidden | `false` |
| `emailTo` | email | (free input) |
| `emailFrom` | email | (free input) |
| `emailRequester` | email | (free input) |
| `fontOption` | radio | (free input) |
| `findText` | text | (free input) |
| `replaceText` | text | (free input) |
| `replaceMatchCase` | checkbox | (free input) |
| `replaceMatchLinks` | checkbox | (free input) |
| `hexcolor` | text | `#FF0000` |
| `color` | text | `#FF0000` |
| `saveSignature` | checkbox | (free input) |
| `stampDateStyle` | select | `none`, `date`, `date-time`, `date-dm`, `date-time-dm` |

### split-pdf-by-outline

- **URL:** https://www.sejda.com/split-pdf-by-outline
- **Title:** Split PDF By Table Of Contents
- **Description:** Split PDF by bookmarks. Extract chapters to separate documents based on the bookmarks in the table of contents. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `splitByBookmarks`
- **Submitted `type`:** `splitByBookmarks`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `bookmarksLevel` | radio | `1`, `2`, `3` |
| `bookmarksExpression` | text | (free input) |
| `includePageAfter` | checkbox | `true` |

### split-pdf-by-size

- **URL:** https://www.sejda.com/split-pdf-by-size
- **Title:** Split PDF by file size
- **Description:** Split PDF by file size. Get multiple smaller documents with specific file sizes. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `splitBySize`
- **Submitted `type`:** `splitBySize`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `size` | text | `1.5` |
| `sizeUnit` | radio | `MB`, `KB` |

### split-pdf-by-text

- **URL:** https://www.sejda.com/split-pdf-by-text
- **Title:** Split PDF By Text Content
- **Description:** Split PDF By Text Content. Extract separate documents when specific text changes from page to page. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `splitByText`
- **Submitted `type`:** `splitByText`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `area[x]` | hidden | (free input) |
| `area[y]` | hidden | (free input) |
| `area[width]` | hidden | (free input) |
| `area[height]` | hidden | (free input) |
| `startsWith` | text | (free input) |

### split-pdf-down-the-middle

- **URL:** https://www.sejda.com/split-pdf-down-the-middle
- **Title:** Split PDF Down the Middle A3 to A4 Online
- **Description:** Split PDF pages down the middle. Split two page layout scans, A3 to double A4 or A4 to double A5. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `splitDownTheMiddle`
- **Submitted `type`:** `splitDownTheMiddle`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `ratio` | hidden | `1` |
| `mode` | hidden | `auto` |
| `autoDetectExcludedPages` | checkbox | `true` |
| `excludedPages` | text | (free input) |
| `repagination` | checkbox | `last-first` |
| `rightToLeft` | checkbox | `true` |

### split-pdf

- **URL:** https://www.sejda.com/split-pdf
- **Title:** Split PDF Online. Free and easy to use
- **Description:** Split PDF by pages. Split specific page ranges or extract every page into a separate document. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `splitByPages`
- **Submitted `type`:** `splitByPages`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `mode` | radio | `page`, `file` |
| `thumbsSize` | range | `150` |
| `step` | text | `1` |
| `pages` | text | (free input) |
| `discardOutline` | checkbox | `true` |
| `filename` | text | (free input) |

### unlock-pdf

- **URL:** https://www.sejda.com/unlock-pdf
- **Title:** Unlock PDF Online
- **Description:** Unlock PDF Online. Remove restrictions and password from PDF files. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `decrypt`
- **Submitted `type`:** `decrypt`
- **Accepted files:** pdf
- **Options:** none (file only)

### upgrade

- **URL:** https://www.sejda.com/upgrade
- **Title:** Pricing &amp; Upgrade - Sejda
- **Description:** Select a plan that's right for you
- **Task type (data-task):** none (not a task page)

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `csrf` | hidden | (per-page token, omitted) |
| `password` | password | (free input) |
| `emailVerificationCode` | text | (free input) |
| `agreeTerms` | checkbox | `yes` |
| `seats` | hidden | `1` |
| `discount` | hidden | `0` |
| `stripePublicKey` | hidden | (free input) |
| `paypalEnv` | hidden | (free input) |
| `firstName` | text | (free input) |
| `lastName` | text | (free input) |
| `companyName` | text | (free input) |
| `vatNumber` | text | (free input) |
| `billingAddressCountry` | select | `FR`, `CA`, `BR`, `IN`, `ES`, `US`, `GB`, `AF`, `AX`, `AL`, `DZ`, `AS`, `AD`, `AO`, `AI`, `AQ`, `AG`, `AR`, `AM`, `AW`, `AU`, `AT`, `AZ`, `BS`, `BH`, `BD`, `BB`, `BY`, `BE`, `BZ`, `BJ`, `BM`, `BT`, `BO`, `BQ`, `BA`, `BW`, `BV`, `IO`, `VG`, `BN`, `BG`, `BF`, `BI`, `KH`, `CM`, `IC`, `CV`, `KY`, `CF`, `TD`, `CL`, `CN`, `CX`, `CC`, `CO`, `KM`, `CD`, `CG`, `CK`, `CR`, `HR`, `CU`, `CW`, `CY`, `CZ`, `DK`, `DJ`, `DM`, `DO`, `EC`, `EG`, `SV`, `GQ`, `ER`, `EE`, `ET`, `FK`, `FO`, `FJ`, `FI`, `GF`, `PF`, `TF`, `GA`, `GM`, `GE`, `DE`, `GH`, `GI`, `GR`, `GL`, `GD`, `GP`, `GU`, `GT`, `GG`, `GN`, `GW`, `GY`, `HT`, `HM`, `HN`, `HK`, `HU`, `IS`, `ID`, `IR`, `IQ`, `IE`, `IM`, `IL`, `IT`, `CI`, `JM`, `JP`, `JE`, `JO`, `KZ`, `KE`, `KI`, `KP`, `KR`, `XK`, `KW`, `KG`, `LA`, `LV`, `LB`, `LS`, `LR`, `LY`, `LI`, `LT`, `LU`, `MO`, `MK`, `MG`, `MW`, `MY`, `MV`, `ML`, `MT`, `MH`, `MQ`, `MR`, `MU`, `YT`, `MX`, `FM`, `MD`, `MC`, `MN`, `ME`, `MS`, `MA`, `MZ`, `MM`, `NA`, `NR`, `NP`, `NL`, `NC`, `NZ`, `NI`, `NE`, `NG`, `NU`, `NF`, `MP`, `NO`, `OM`, `PK`, `PW`, `PS`, `PA`, `PG`, `PY`, `PE`, `PH`, `PN`, `PL`, `PT`, `PR`, `QA`, `RE`, `RO`, `RU`, `RW`, `BL`, `SH`, `KN`, `LC`, `MF`, `PM`, `VC`, `WS`, `SM`, `ST`, `SA`, `SN`, `RS`, `SC`, `SL`, `SG`, `SX`, `SK`, `SI`, `SB`, `SO`, `ZA`, `GS`, `SS`, `LK`, `SD`, `SR`, `SJ`, `SZ`, `SE`, `CH`, `SY`, `TW`, `TJ`, `TZ`, `TH`, `TL`, `TG`, `TK`, `TO`, `TT`, `TN`, `TR`, `TM`, `TC`, `TV`, `UG`, `UA`, `AE`, `UM`, `VI`, `UY`, `UZ`, `VU`, `VA`, `VE`, `VN`, `WF`, `EH`, `YE`, `ZM`, `ZW` |

### watermark-pdf

- **URL:** https://www.sejda.com/watermark-pdf
- **Title:** Watermark PDF Online
- **Description:** Add image or text watermark to PDF documents. Online, no installation or registration required. It's free, quick and easy to use.
- **Task type (data-task):** `watermark`
- **Submitted `type`:** `watermark`
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `key` | hidden | (free input) |
| `AWSAccessKeyId` | hidden | (free input) |
| `acl` | hidden | (free input) |
| `success_action_redirect` | hidden | (free input) |
| `policy` | hidden | (free input) |
| `signature` | hidden | (free input) |
| `Content-type` | hidden | (free input) |
| `x-amz-storage-class` | hidden | (free input) |
| `pageLocation` | radio | `centered`, `custom` |
| `fontSize` | text | (free input) |
| `color` | text | `#000000` |
| `imageWidth` | text | (free input) |
| `imageHeight` | text | (free input) |
| `previewPageNumber` | text | `1` |
| `jsonData` | hidden | (free input) |
| `pages` | hidden | (free input) |
| `opacity` | range | `100` |
| `watermarkText` | textarea | (free input) |

### word-to-pdf

- **URL:** https://www.sejda.com/word-to-pdf
- **Title:** Convert Word DOC to PDF online
- **Description:** High quality free conversion from Word to PDF online
- **Task type (data-task):** `docToPdf`
- **Submitted `type`:** `docToPdf`
- **Accepted files:** docx,doc
- **Options:** none (file only)

### workflows

- **URL:** https://www.sejda.com/workflows
- **Title:** Workflows with PDF documents
- **Description:** Execute series of tasks on PDF documents. Configure task chains to process PDFs. Free, no watermarks or registration. Batch convert multiple files.
- **Task type (data-task):** none (not a task page)
- **Workflow page:** true
- **Accepted files:** pdf

| Field | Input kind | Values seen in HTML |
|---|---|---|
| `workflowId` | hidden | (free input) |
| `automaticStart` | checkbox | `true` |
