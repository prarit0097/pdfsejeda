# Sejda.com: runtime observation (agent 1)

Observed 2026-10-21 with REA `capture_browser_scenario` (launch mode, headless Microsoft Edge 155 / Chromium, temp profile, en-US, UTC). REA performed the declared actions (clicks/fills) in the browser. Static findings in `SEJDA-REVERSE-ENGINEERING.md` are not repeated except where runtime confirms or corrects them.

**Load on Sejda:** 10 page-load scenarios, **2 tasks** in total (1 `compress`, 1 `edit`), both on a public 13 KB one-page test PDF (`https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf`). No paywall, captcha (430) or 429 was hit. After the 2nd task the server reported `x-ratelimit-remaining: 1`. No login, no fuzzing, and no hand-made API calls: every `/api` request below was made by Sejda's own UI.

**Key:** **[observed]** = seen in captured traffic, DOM or screenshot. **[inferred]** = deduced. **[unknown]** = not determined. Shipped-JS reads done to explain runtime behaviour are marked **[observed-js]** (`result.min.js?v=132` captured at runtime; `libs-and-partials.min.js` cache 649; `pdf-editor.min.obfuscated.js?v=523`).

**Redactions:** cookie values are hashed or redacted by REA. The page's `data-proxy-token` / `x-proxy-token` / `_xpt` value and the download signature `s=web-…` are shortened to `<…>` below.

## Evidence index

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

## 0. Methodology limitation: local file upload

The REA scenario action set (goto/click/fill/press/select/check/wait) has **no set-input-files or drag-drop action**, so a local file could not be pushed into `<input type=file>`. As a result, **`/api/files/upload-check`, `/api/files/upload` and `/api/files/upload-chunked` were not exercised at runtime** **[unknown at runtime]**. Their static description stands.

Instead I used the UI's own **"Web Address (URL)"** import (compress) and the **`?files=[{"downloadUrl":…}]`** page parameter (editor). The site itself builds that parameter in `result.min.js` (`publish-gdrive` → `sign-pdf?files=`). Both paths register the file with a different endpoint, described in §2.1.

---

## 1. Results page (`result?id=…`)

### 1.1 How it is opened [observed, ev_2f62afc4…, ev_5145c770…]

1. `POST /api/tasks` → 200, body = JSON string task id, e.g. `"YHLFMUJQ-202610211908"`.
   - **Task id format:** `<8 uppercase alnum>-<yyyyMMddHHmm>`, with the timestamp in the server's timezone (UTC+1/+2 vs the browser's UTC) **[inferred]**.
2. The top page URL hash becomes `#results-<taskId>` (e.g. `compress-pdf?#results-YHLFMUJQ-202610211908`).
3. An iframe named **`_results`** navigates to `https://www.sejda.com/result?id=<taskId>`.

### 1.2 Scripts the result page loads [observed]

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

### 1.3 Polling [observed + observed-js]

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

### 1.4 Download URL formation [observed + observed-js]

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

### 1.5 Other result-page endpoints [observed-js only, not called]

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

## 2. Requests and responses

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

### 2.1 Registering a remote file: `POST /api/files` [observed, ev_2f62afc4…, ev_5145c770…]

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

### 2.2 Preview proxy: `GET /api/files/client-view?url=<enc>` [observed]

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

### 2.3 `POST /api/tasks`: compress [observed, ev_2f62afc4…]

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

### 2.4 `POST /api/tasks`: edit (one added text box) [observed, ev_5145c770…]

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

### 2.5 Status and download

See §1.3 and §1.4. No other status or progress endpoints were called **[observed]**.

**Endpoints not called:**
- `POST /api/tasks/<id>/cancel` was not called, because the modal was not closed **[unknown at runtime]**.
- `POST /api/files/<id>/touch` was **not** observed within about 50 s on the page **[observed absence within the window; interval unknown]**.

### 2.6 Upload endpoints

`/api/files/upload-check`, `/api/files/upload?_s=&uplid=…` and `/api/files/upload-chunked` were not exercised (see §0) **[unknown at runtime]**.

The **`uplid`** is rendered into the page per load, e.g. `OSNWO10211904`: 5 letters plus MMddHHmm. The form `action` is `https://www.sejda.com/api/files/upload?_s=&uplid=OSNWO10211904` and the file input is `name="file"` **[observed DOM, ev_fdff1b3a…]**.

---

## 3. pdf-editor at runtime [observed, ev_050e3c00…, ev_5145c770…]

### 3.1 Requests when a PDF is opened, in order

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

### 3.2 Editor DOM facts [observed]

- `#task-content[data-task="edit"][data-multiple-files="false"][data-free-max-file-size="100"]`.
- The task form (`.task-form`) holds hidden `type=edit`, `elapsedTime`, `recovered=false`, `outputFilenamePattern` and `files[]=<fileId>`. The submit button is `#save-pdf-btn` "Apply changes".
- Pages render as `.page-wrap.rendered` with `canvas.page`. The pages container is `#edit-pages-wrap`, not `#edit-pages`.
- The active tool sits on `#edit-pages[data-tool="text"]`. Text is the default tool.
- A new text box is a `.text-editable[contenteditable=true]` with a floating `#text-editable-menu`: bold, italic, size, font, colour, link, move, clone, delete.
- Modals in the DOM include `#removeUnusedTextPrompt` ("Found 'Type your text' edits…") and `#recoveryPrompt` ("Recover unsaved changes").

### 3.3 Result

The edit task used the identical result-iframe, poll and download flow (§1). The output was 12,960 bytes vs 13,264 input **[observed]**.

---

## 4. Cookies, storage, third parties

### Cookies (names only) [observed, ev_fbd7ca66…, ev_2f62afc4…, ev_5145c770…]

| Cookie | Domain | Flags |
|---|---|---|
| `clientId` | `.sejda.com` | SameSite Lax, not HttpOnly, not Secure. Set on first page load. |
| `_s` | `.sejda.com` | SameSite Lax, not HttpOnly. Set on first page load. Same name as the `_s=` query param **[inferred related]**. |
| `lang` | `www.sejda.com` | |
| `JSESSIONID` | `www.sejda.com` | **HttpOnly**. Appears after the task / `/change` response, which suggests a Java servlet backend **[inferred]**. |

The cookies `upgradeReason`, `upgradeRefTask` and `upgradeReturnUrl` are set only on a paywall result **[observed-js, not triggered]**.

### localStorage keys [observed]

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

### Third-party / other hosts contacted [observed]

- **`a.sejda.com`:** only `GET /js/pa-pTbOttubxy_kKIavRgNtA.js`, once per document, including inside the result iframe. **No analytics beacon request was observed** in the windows captured **[observed absence; beacon timing unknown]**.
- **`www.w3.org`:** only the test PDF I chose (browser CORS attempt).
- **Nothing else:** no Google, Sentry, FastSpring, Stripe or Dropbox requests on compress-pdf, pdf-editor or result pages without user interaction.
- **Cloudflare:** fronts everything (`cf-ray`, NEL `report-to a.nel.cloudflare.com`, but no NEL report was sent).

### Other runtime notes [observed]

- Static assets are served with `cache-control: public, max-age=2678400` (31 days) from the Cloudflare cache (`cf-cache-status: HIT`).
- The shared bundle cache key is **649** (the static report saw 149, which is still PDF.js's cache path).
- Page HTML is `no-cache, private, no-store`.

---

## 5. Still unknown

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
