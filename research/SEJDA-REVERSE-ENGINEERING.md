# Sejda.com: reverse-engineering report

Analysed on 2026-10-21 using REA plus static analysis of the public HTML/JS. Nothing was executed against Sejda's servers beyond normal page/script downloads (robots.txt crawl-delay respected; `/api/` was never called).

Machine-readable catalog of every tool and its form options: [sejda-tools-catalog.json](sejda-tools-catalog.json)

**Second pass (3 parallel REA agents), with full detail in:**
- [agent-1-runtime.md](agent-1-runtime.md): live browser capture of 2 real tasks (compress, edit). Covers the results page, polling, download URLs and real payloads.
- [agent-2-static.md](agent-2-static.md): the editor fully deobfuscated. Covers JSON schemas for all editor operations, task serialization, page-selection encoding, workflows, login and storage.
- [agent-3-desktop.md](agent-3-desktop.md): Sejda Desktop 7.9.11 taken apart. Covers the Java engine stack, the task-type → engine-class map, and which features are server-only.

Sections below are updated with their findings. Anything the second pass corrected is marked **(corrected)**.

**Confidence key:** **[seen]** = read directly in shipped HTML/JS. **[inferred]** = deduced from names or strings and not verified. **[unknown]** = not visible from the client side.

---

## 1. Architecture in one picture

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

## 2. Front-end stack [seen]

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

## 3. Tool page anatomy [seen]

Every tool page contains:

- `#task-content` with `data-task="<type>"` (and `data-workflow` for workflow runs).
- An upload form `#fileUploadForm` with `action=/api/files/upload?_s=&uplid=<random>`, `data-filetypes`, `data-chunked-uploads`, `data-parallel-chunked-uploads`, `data-max-file-size="500"` and `data-free-limit-file-size`.
- `form.task-form` holding a hidden `type`, the tool's options, and `files[]` hidden inputs that are added as uploads finish.
- Per-file password prompts (`filePwd`, `usePwdForAllFiles`). **(corrected)** Passwords are not part of the task JSON. They are saved separately with `POST /api/files/<id>/password`.
- "More options" toggles, a recent-files list (IndexedDB, `source:"sejda_task_result"`) and a support/contact form. The support form can attach console logs, a screenshot, OS info and `allowAccessLastTask`.
- A hidden field `suflet=iluzie` [seen]. It has a constant value, so it is probably a bot/honeypot marker [inferred].

## 4. Upload pipeline [seen]

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

## 5. Task execution [seen]

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

## 6. Every tool: task type and options [seen]

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

## 7. PDF editor internals (`pdf-editor`, `pdf-forms`, `sign-pdf`) [seen, from decoded strings]

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

## 8. Business rules / limits [seen in page text]

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

## 9. The engine, as seen in Sejda Desktop 7.9.11 [seen, from agent 3]

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

## 10. Third pass: live verification ([live-verification.md](live-verification.md))

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

## 11. Building your own version: recommendations (my suggestions, not observed)

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
