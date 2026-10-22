# Sejda PDF Desktop 7.9.11 (Windows x64): static teardown of the local engine

Analysed on 2026-10-21. Nothing was installed or executed: the official portable ZIP was unpacked with `unzip`, `app.asar` was unpacked with a small Python reader, and jar contents were listed (manifests, `pom.xml`/`pom.properties`, config XML, class names and constant-pool strings only). No large-scale decompilation was done.

Confidence key: **[seen]** = read directly in the shipped artifact. **[inferred]** = deduced from names or strings. **[unknown]** = not determinable statically.

Builds on: [SEJDA-REVERSE-ENGINEERING.md](SEJDA-REVERSE-ENGINEERING.md) (web analysis).

---

## 1. Artifact identity

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

## 2. Architecture

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

## 3. Component inventory

### 3.1 Bundled runtimes and native tools [seen]

| Component | Version | Notes |
|---|---|---|
| Electron / Chromium | 42.4.0 | `LICENSE.electron` (MIT), `LICENSES.chromium.html` |
| Java runtime | **JDK 25.0.3**, a jlink image | `resources\vendor\jdk25-windows-x64`. Modules: java.base, desktop, xml, sql, naming, scripting, management, security.jgss/sasl, xml.crypto, prefs, rmi, logging, compiler, jdk.compiler, jdk.javadoc, jdk.zipfs, jdk.internal.md/opt. The vendor is not stated in the `release` file [unknown]. |
| Tesseract OCR | **4.0.0.20190314** (`libtesseract-4.dll`), MinGW build | Ships with leptonica (`liblept-5`), libtiff-5, libpng16, libjpeg-8, libwebp-7, openjp2, giflib, glib/gobject, libgomp. Only `eng.traineddata` is bundled. Other languages are downloaded on demand from `https://sejda-cdn.com/downloads/tessdata/<lang>.traineddata` into `%APPDATA%\sejda-desktop\tessdata`. |
| Ghostscript, LibreOffice, qpdf, Chromium/wkhtmltopdf for HTML→PDF, ImageMagick | **absent** | Not present anywhere in the file tree [seen]. |

### 3.2 Java classpath (`resources\vendor\desktop-launcher\lib`, 74 jars) [seen]

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

## 4. Task type → engine mapping

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

## 5. Licensing and limits (high level only)

- **Verify endpoint** [seen]: the renderer calls `POST https://www.sejda.com/licenses/verify` (`$.jsonPost`, `sejdaBase = "https://www.sejda.com"`) with JSON `{id: "com.sejda.sejda-desktop", version, hostname, username, hostSerial: "", licenseKey}` (built by `preload.js` `licensing.getLicenseData` and `lib/computer-id.js`). Responses such as `expired` and `access_revoked` show dedicated screens. A per-session flag `sessionStorage.licenseVerified` avoids re-verifying.
- **Stored locally** [seen]: `%APPDATA%\sejda-desktop\prefs.json` (older builds used `~/.sejda`) holds `licenseKey`, `licenseExpires`, `licenseToken`, plus UI preferences. The log is `%APPDATA%\sejda-desktop\sejda-desktop.log`.
- **Enforcement point** [seen/inferred]: each task JSON gets `key` and `token` added from prefs. Inside the JVM, `code.limits.LicenseInformation` decodes the encrypted token (it carries an expiry) and `DesktopPlanLimits` decides whether to return `upgrade` (free-tier limits such as file count, page count, image size and hourly task meters). Counters are stored on disk via `code.util.ratelimit.DiskPersistentMeter`. `UntrustedLocalClock` compares local time with internet time over NTP (commons-net) to detect clock tampering. Mechanism internals were deliberately not examined further.
- **Other outbound calls** [seen]: `GET /news/desktop?…`, the contact/bug report at `https://www.sejda.com/contact` (opt-in; it can attach the last task JSON with file passwords masked), and tessdata downloads from sejda-cdn.com.

## 6. REA Evidence IDs

| ID | What |
|---|---|
| `ev_8023f694984d3d4f018511d50ce11da057f6d45a8106a02febcf7e384e8ba517` | `inspect_electron_fuses` on `Sejda PDF Desktop.exe` |
| `ev_bb55139d2817495ebdfc66b3f12e73758e78e5d370e9ca805de15d07b7f67c4c` | `analyze_javascript_application` on `app.asar`: 943 JS files parsed; 1 BrowserWindow config, 1 contextBridge API (50 members), 10 literal IPC channels all paired. Coverage was partial: `pdf.worker.min.js` was not analysed semantically. |
| `ev_cb0b46a858b913338161fc195cdeac9483c7bbf11cc7caa40595eae3c47161f7` | Summary view of the above |

Jar, ZIP and asar facts come from direct static reads (`unzip -l`/`-p`, plus Python scripts in `agent-desktop\tools\`: `asar_x.py`, `jstr.py`, `ids.py`), not from REA Evidence.

## 7. Still unknown

- The MSI contents were not unpacked (no 7-Zip, no msiexec allowed). It is assumed identical to the portable ZIP [inferred].
- The exact JSON schema of `task.out` beyond `status`, `failureReason`, `upgrade` and the result file list.
- The algorithms inside `EditTask`, `OptimizeTask` and `TableDetector`, and the exact free-tier thresholds in `DesktopPlanLimits` (not decompiled by design).
- Upstream license of the sejda-core/model/sambox 5.1.23 jars (parent POM not shipped) and of `com.sejda.common`/pro jars (proprietary; no license file in them) [unknown].
- The JDK vendor/distribution, and the Tesseract build origin and Leptonica version.
- The server-side engine for `htmlToPdf`, `pdfToOfficeWord`, `pdfToOfficeExcel`, `pdfToPpt` and `docToPdf` (no local implementation to observe).
- Whether the Mac and Linux builds differ. `desktop-launcher.js` shows Linux uses the system Tesseract (`useEmbeddedOcr = !isLinux`) [seen].
- Runtime behaviour: nothing was executed, so heap retries, actual network calls and the progress protocol are known only from static code.
