# PDFNova regression pool

Read [TEST-PLAN.md](TEST-PLAN.md) for scope, execution order and the per-tool matrix.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe scripts/run_test_pool.py
```

Linux uses `python`/`python3` from the active environment. Install LibreOffice,
Tesseract English data and Chromium system libraries to verify real engines.
The existing project guide lists local setup and licensed dependencies.

The runner starts its own loopback server on a free port with temporary data,
disabled hourly quota and dotenv loading disabled. It stops only that process
tree afterward. It does not use the developer's server, files or production.
Run one pool at a time: older browser scripts share generated screenshot folders.

Each run creates `data-qa-pool/runs/<UTC timestamp>/results.json`, per-stage logs,
JUnit XML, branch coverage JSON and browser inventories. These are ignored by
Git; all fixtures are generated. CI retains the run folder as an artifact. CI
configuration being present is not evidence of a successful hosted CI run.

Stages:

| Stage | What it verifies |
|---|---|
| Python | All existing semantic/security tests; every page/option/asset contract; all 43 canonical tools through actual HTTP task lifecycle and parsed outputs; missing/invalid inputs and PDF range serving |
| All-tool UI (desktop + mobile) | All 43 visible UI submissions at each viewport with output parsing; 160 declared control interactions at each viewport; all 51 public page shells at mobile size |
| Shared features | Categories/search/theme, upload errors/remove/reset, private URL rejection, required selection, workflow import/export/rename/run/delete |
| Existing browser | Full page navigation plus representative thumbnails, results, continuing, metadata, bookmarks, crop, mix, HTML and mobile flows |
| Editor | Draft/recovery/undo/find-replace, advanced forms, storage restrictions, workflows and touch editing with real PDF output |
| Signatures | Library/type/draw/upload/camera, object actions, cursor preview, one-time placement and saved outputs |
| Signature cleanup | Nine generated ink/paper cases plus actual PNG/preview/PDF RGBA equality and single-placement checks |
| Concurrency | Sixteen simultaneous generated PDF tasks, parsed results and task cleanup |

`--include-network` additionally runs the existing live smoke suite with public
HTML/PDF fixture fetches. Network/DNS/remote-site failures are reported as failures,
not hidden. The default pool uses generated content and local browser requests;
optional interface font requests may still occur, with bundled signature fonts.

Useful focused commands against an isolated development server:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_tool_catalogue.py -q
$env:POOL_TOOL_FILTER='pdfToImage'
.venv\Scripts\python.exe scripts/tool_ui_regression.py http://127.0.0.1:18088
Remove-Item Env:POOL_TOOL_FILTER
```

Do not run the exhaustive pool against public production: it submits many tasks,
can consume quota and compete with real document jobs. Use only bounded public
checks after releasing application fixes.

Coverage counts have different granularity and must be reported separately.
Rendering or changing an option is not proof of every semantic option branch.
Generated documents do not establish arbitrary-file conversion fidelity, every
option combination, sustained load, physical camera behavior or other browsers.
