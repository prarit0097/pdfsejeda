# Sejda.com: static deobfuscation and payload schemas (agent 2)

Date: 2026-10-21. Method: static parsing only. The target JavaScript was never executed: no eval, no node `require` of target files, and the obfuscator's own rotation IIFE was not run. Tooling: @babel/parser, @babel/traverse and @babel/generator, installed in the scratch workspace, plus REA.

Confidence key: **[seen]** = read directly in the deobfuscated or prettified code. **[inferred]** = deduced and not verified. **[unknown]** = not visible client-side.

Builds on `SEJDA-REVERSE-ENGINEERING.md`. This report corrects two points in it, marked **(correction)**.

## 0. Artifacts produced (scratch)

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

## 1. Deobfuscation of `pdf-editor.min.obfuscated.js` [seen]

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

## 2. Editor save model (types `edit` and `fillSign`) [seen]

### 2.1 Flow

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

### 2.2 Coordinate system and units [seen unless noted]

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

### 2.3 Operation schemas (one JSON object per array entry) [seen]

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

### 2.4 Final `/api/tasks` body for the editor [seen]

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

## 3. libs-and-partials: form serialization and platform services

### 3.1 `form.task-form` → `/api/tasks` [seen, L26545–26745]

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

### 3.2 Workflows [seen, L23772–23930, @685838; L26756–26810]

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

### 3.3 Login, account and session [seen, L24400–24500, @707350/@708417]

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

### 3.4 Recent files (IndexedDB) [seen, L25840–26035, @755168]

- **Storage:** a Dexie database `recent-files`. Version 1 has the store `recentFiles: "id,name,mimeType,createdTime,folderId,cachedAt"`; version 2 adds `source,filesParam,taskUri`.
- **Two sources:**
  - `source:"gdrive_app_folder"`: up to 50 files from the user's Google Drive folder **`SejdaPDF`**, listed with Drive v2 `files.list`.
  - `source:"sejda_task_result"`: added by `Sejda.RecentFiles.addRecentTask({id: taskId, resultFilename, name, resultFilesParam, taskUri, resultDlUrl})`. This is called from the results iframe.
- **Task-result records:** `filesParam` is JSON of link-file descriptors and `downloadUrl` is the result URL. They are purged 50 minutes after creation.
- **Deleting a record:** removes it locally and calls `DELETE /api/tasks/<id>`.
- **Panel:** `localStorage general.recentFilesPanel.dontShow` hides the panel.

### 3.5 Cloud import/export [seen, L23980–24210, L25495–25585]

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

### 3.6 Captcha [seen L26835–26840, @793604]

- **Trigger:** HTTP 430. The client stores the body in `window.lastCaptchaFormData` and opens the iframe page **`captcha`** in the results modal.
- **Callback:** that page calls `window.top.captchaCallback(token)`, which resubmits the same body with `captchaToken`.
- **Provider [unknown]:** no hCaptcha, reCAPTCHA or Turnstile strings appear in any downloaded page or bundle, so the provider lives only in the `/captcha` page.

### 3.7 Analytics [seen, L22341, @639371]

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

## 4. Page selection and thumbnails (organize / rotate / delete / split) [seen]

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

## 5. Still unknown

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
