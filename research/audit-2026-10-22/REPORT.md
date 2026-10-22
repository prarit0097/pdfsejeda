# PDFNova verification and Sejda parity audit — 2026-10-22

The local app has 43 registered PDF tools. This pass preserved and integrated the
existing working-tree implementation, repaired defects, added missing capabilities,
and verified actual downloaded documents. It does **not** establish an exact clone
of every Sejda page, account service, platform, or visual detail.

## Verification results

| Check | Result | What was checked |
|---|---:|---|
| Clean Python environment | 170 passed | Full pytest suite under a new Windows x64 Python 3.13 virtual environment |
| Dependency integrity | Passed | `pip check`; tested versions retained in `requirements-lock.txt` |
| Live HTTP smoke | 58/58 | All tool groups, actual output downloads, LibreOffice, Tesseract, Chromium, upload/continue/signatures |
| Generic browser suite | 62/62 | All 43 tool pages, seven ancillary pages, search/theme/menu, actual browser downloads, continuation, mix/crop controls, mobile and externally blocked previews |
| Editor browser suite | 8 scenario groups passed | Failure recovery, structural drafts, find/replace, advanced forms, filling, workflow encryption, unavailable browser storage, active mobile editing |
| Concurrent HTTP jobs | 16/16 | Simultaneous crop, flatten, images, deskew, PPT, text, extraction and rotation; outputs inspected |
| Syntax/package checks | Passed | JavaScript syntax, Python compilation, diff whitespace, vendored asset hashes |
| Docker build | Unverified | Docker CLI is absent; image configuration reviewed and repaired |

The final Python run reported two dependency/test deprecation warnings (Starlette's
HTTPX adapter and a Pillow assertion helper), with no failing tests. Synthetic
fixtures are intentionally small and do not prove fidelity for every PDF in the wild.

Commands, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/smoke_test.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/browser_regression.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/concurrency_regression.py http://127.0.0.1:8000
.\.venv\Scripts\python.exe scripts/editor_regression.py
```

The first three HTTP scripts need a running server; the editor script starts its own
isolated server. Local screenshots/results are in `data-qa-browser/` (git-ignored).

## REA evidence and scope

REA 6.7.0 CLI was already installed. Its MCP tools were unavailable in this Codex
session, so the supported CLI browser scenario workflow was used without changing
client registration or installing native decompilers.

- Public-site evidence: `ev_98b257ce76f31fd1e36489778d95c6009a1d8c8d3a2f53bd9630855a447ab558`.
  Eight pages were navigated: home, compress, merge, editor, forms, crop, HTML and
  workflows. DOM, final accessibility/screenshot and console observations were
  captured. No PDF processing tasks were submitted to Sejda in this pass.
- Local runtime evidence: `ev_e0c096521c18196b571be1afad4928850de8fc88124d5098bdf906607359d1fb`.
  REA performed URL import of the public W3C dummy PDF, submitted compression,
  waited for completion and opened the preview. All 11 recorded steps completed.
- Both successful records report complete capture without omitted/truncated
  sections. This describes capture completeness, not product equality.
- The first local attempt failed on a test selector that assumed an explicit
  submit-button type. The corrected selector completed the same intended flow.
- Compact provenance is retained in `rea-summary.json`, `rea-local-summary.json`
  and the scenario input JSON files. Complete original Evidence stays locally in
  ignored `rea-*-evidence.json`, because DOM/network observations can include
  ephemeral service tokens. No Sejda application code was copied into the app.

The existing 49-page research catalog contains all 43 core tool slugs implemented
locally plus ancillary product/documentation pages. Catalog field names are
evidence of controls, not proof of server behavior or required wire equality.
The live [Sejda homepage](https://www.sejda.com/) confirms a broader product surface
including pricing, desktop, login, cloud services and language-specific pages.

## Repairs and added capabilities

1. **Job/access/storage:** task IDs now contain 160 random bits; bounded job
   admission happens before file IO; rejected tasks refund quota. Queue cancellation,
   expiry, timeout capacity, partial-output cleanup, missing/corrupt storage,
   atomic metadata writes and continuation rollback have regression coverage.
   IDs are explicitly documented as bearer capabilities; signatures are not an
   independent ownership check.
2. **Native concurrency:** PDFium access and explicit queue garbage collection share
   a reentrant lock. This follows its documented
   [thread incompatibility](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading).
   Unrelated processing remains concurrent. Native handles must remain inside the
   guarded document scope.
3. **Word conversion:** a valid DOCX triggered a real Windows LibreOffice crash
   with long task-derived profile paths. Short isolated paths and the console
   launcher fixed it. DOCX/TXT can fall back with a warning if the engine fails;
   genuine LibreOffice conversion is separately tested without allowing fallback
   to mask integration failures.
4. **HTML conversion:** public IP pinning covers every resource and redirect hop.
   HTTPX ignores proxy environment variables and strips credentials across hosts.
   Tests caught Playwright bypassing interception for redirect follow-ups; those
   redirects now resolve inside the controlled fetcher. Top-level final URL/origin
   and redirected CSS/image paths are preserved. Network WebSockets and service
   workers are blocked. Added language, timezone, print details, bounded ads/notice
   filtering and strict/partial load handling. Live example.com and Python.org
   conversion, including python.org redirects and 29 resources, succeeded.
5. **Editor/recovery:** drafts use a document-byte hash, survive failed saves and
   recover structural-only changes; only completed saves clear the saved revision.
   Expired/corrupt drafts are pruned. Find/replace supports adjacent horizontal text
   fragments, case matching, selected/all replacements, undo and recovery. Existing
   text remains beneath visual edits; this is not secure redaction.
6. **Forms:** text, checkbox, dropdown, listbox and grouped radio creation/filling;
   export/display option pairs, multiselect, defaults, required flags, character
   limits and comb fields. Generated appearances were checked at all four page
   rotations, and browser tests inspect saved PDF values.
7. **Workflows:** record completed steps, scrub credentials from persisted/imported/
   exported chains, request encryption passwords at runtime and propagate necessary
   intermediate unlock values in memory. Browser-storage failures do not block
   processing.
8. **UI/tools:** per-source mix steps/reversal/rotation and individual/odd-even crop
   regions. Active mobile editor toolbar labels and touch targets were enlarged;
   real touch editing, scrolling, save and downloaded content were verified.
9. **Packaging/docs:** self-hosted official
   [PDF.js 6.4.299](https://github.com/mozilla/pdf.js/releases/tag/v6.4.299) with its
   notices, worker, CMaps, fonts and codecs; no preview CDN dependency. Added actual
   developer guides and result reopening. Docker uses the tested dependency snapshot
   and a shared Chromium path; secrets, virtual environments and QA data are excluded
   from its build context.

## Remaining exact-parity gaps

User scope clarification: accounts/billing, cloud integrations and email signing are
deferred for now. Their absence is not a blocker for the current delivery. Local PDF
signatures, URL imports and local workflows remain included.

The following remaining items are not implemented or not established by the tests above:

- Sejda's exact visual design, branding, copy, tutorial library and all marketing
  routes. PDFNova retains its original interface and identity.
- A native desktop distribution and browser extensions.
- Translated routes and complete multilingual product copy.
- Exact arbitrary-document conversion fidelity: Word/Excel reconstruction is
  heuristic; PPT slides contain page images; original embedded-font editing is
  absent. Find/replace handles horizontal text runs, not arbitrary vertical or
  transformed text. Original text can remain extractable beneath edits.
- Some advanced controls from the source research, including font subsetting,
  fully interactive bookmark-tree editing, arbitrary watermark placement and
  exact per-source repeat semantics. They require further implementation and
  evidence rather than assuming matching control names proves matching behavior.
- US/EU hosted-browser location selection, automatic HTML print orientation,
  authenticated browser sessions and perfect handling of redirected module scripts.
  Banner/ad filtering is heuristic, not a universal remover.
- Multi-process/shared durable job storage, aggregate disk quotas, hard termination
  of hung native work, production load testing and a verified Linux/Docker build.

The verified deliverable is a substantially repaired local PDF toolkit. These
remaining items prevent calling it an exact, complete Sejda service clone.

Deferred services (excluded by user): login/accounts, paid plans/subscriptions,
payment/account/license management, cloud OAuth pickers/export and email signing.
The earlier audit identified their absence; this is now an explicit scope choice.
