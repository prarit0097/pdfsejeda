# Full application test plan

Date: 2026-10-22. Scope: PDFNova in this repository. Accounts/billing, cloud integrations and email signing remain excluded by the owner. This is a coverage plan, not a claim that arbitrary documents or every option combination can be proven correct.

## Inventory and gates

Current inventory: 43 tools, 160 declared option fields, six information pages, home, workflows, result redirect/expiry and unknown-page handling.

1. Inventory: explicit scenario for every registered tool; fail when a new tool lacks a scenario. Check all pages and all declared form fields/choices, local assets and navigation.
2. Backend: retain existing semantic PDF/security/form tests; add real HTTP upload -> task -> poll -> signed download -> parsed output scenarios for every tool. Check empty/unsupported/missing inputs and malformed requests. Parse real output content, pages, dimensions, fields, encryption and archive contents rather than accepting HTTP 200 alone.
3. Browser: desktop/mobile page inventory; submit all tool families at desktop and mobile viewports through their visible UI, exercising ordinary options, thumbnails, upload/URL/blank entry where applicable. Existing dedicated editor/signature suites cover tools, advanced forms, drafts, undo, placement, cursor preview, RGB/alpha and actual saved PDFs. Additional shared features cover search/categories, theme, navigation, URL dialog, workflows and result chaining.
4. Engines: verify local capabilities; exercise Chromium HTML printing and Tesseract OCR. If an engine is absent, record an explicit skip/limitation and run its semantic checks in an isolated production-equivalent server container. Never call a fallback exact LibreOffice verification.
5. Runner: provide one repeatable command, isolated data directory, bounded timeouts, structured stage results and coverage inventory. Run suites against an isolated local server; never point the full pool at quota-limited public production.
6. Repair: reproduce failures, correct application bugs, add regression assertions, rerun affected suites and the complete final pool. Record counts, failures, skips and limitations honestly.
7. Release: only deploy actual application fixes after passing relevant checks; keep existing shared-server applications untouched. Public checks are bounded. Keep private documents, tokens, raw logs and screenshots out of Git.

## Execution order

- [x] P0: Save inventory and plan before implementation.
- [x] P1: Add missing page/option/asset and API contract tests.
- [x] P2: Add explicit all-tool semantic/API scenario catalogue.
- [x] P3: Add all-tool UI submissions and shared browser features.
- [x] P4: Add repeatable runner and structured report.
- [x] P5: Run, repair, repeat and publish tested coverage and remaining limits.

## Tool coverage matrix

| Task type | Page | Declared options | Verification requirement |
|---|---|---:|---|
| `merge` | `/merge-pdf` | 8 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `splitByPages` | `/split-pdf` | 5 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `splitByBookmarks` | `/split-pdf-by-outline` | 3 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `splitBySize` | `/split-pdf-by-size` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `splitByText` | `/split-pdf-by-text` | 1 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `splitDownTheMiddle` | `/split-pdf-down-the-middle` | 6 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `alternateMix` | `/alternate-mix-pdf` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `extractPages` | `/extract-pdf-pages` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `deletePages` | `/delete-pdf-pages` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `combineReorder` | `/organize-pdf` | 1 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `rotatePages` | `/rotate-pdf-pages` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `compress` | `/compress-pdf` | 4 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `crop` | `/crop-pdf` | 9 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `resizePages` | `/resize-pdf` | 9 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `nup` | `/n-up-pdf` | 4 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `flip` | `/flip-pdf` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `grayscale` | `/grayscale-pdf` | 3 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `deskew` | `/deskew-pdf` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `flatten` | `/flatten-pdf` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `repair` | `/repair-pdf` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `headerFooter` | `/header-footer-pdf` | 8 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `pageNumbers` | `/page-numbers-pdf` | 8 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `batesNumbering` | `/bates-numbering-pdf` | 12 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `watermark` | `/watermark-pdf` | 11 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `encrypt` | `/encrypt-pdf` | 4 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `decrypt` | `/unlock-pdf` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `editMetadata` | `/edit-pdf-metadata` | 9 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `editBookmarks` | `/pdf-bookmarks` | 1 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `deleteAnnotations` | `/delete-pdf-annotations` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `renameByText` | `/rename-pdf` | 1 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `pdfToImage` | `/pdf-to-jpg` | 5 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `jpgToPdf` | `/jpg-to-pdf` | 7 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `extractImages` | `/extract-images-from-pdf` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `extractText` | `/extract-text-from-pdf` | 2 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `pdfToExcelNext` | `/pdf-to-excel` | 3 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `pdfToOfficeWord` | `/pdf-to-word` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `pdfToPpt` | `/pdf-to-ppt` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `docToPdf` | `/word-to-pdf` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `htmlToPdf` | `/html-to-pdf` | 15 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `ocr` | `/ocr-pdf` | 3 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `edit` | `/pdf-editor` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `fillSign` | `/sign-pdf` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |
| `editForms` | `/pdf-forms` | 0 | Page + option contract + semantic API result; browser submission or dedicated editor suite |

## Existing test layers to preserve

- `tests/`: current 170 Python cases, semantic PDF structures and pixels, security/SSRF, chunks/retries, queue/cancellation/expiry, advanced forms, conversions and organization.
- `scripts/smoke_test.py`: live HTTP scenarios; some existing result checks are only smoke checks and need stronger catalogue coverage.
- `scripts/browser_regression.py`: all tool page shells and representative workflows.
- `scripts/editor_regression.py`: eight editor scenario groups.
- `scripts/signature_regression.py`: four signature groups including cursor preview, single placement, actions and saved output.
- `scripts/signature_cleanup_regression.py`: ten generated photo/colour/placement checks.
- `scripts/concurrency_regression.py`: bounded concurrency and queue/resource checks.

## Reporting rules

Track page rendering, declared option presence/interaction, successful tool submission, semantic output validation and deep feature scenarios separately. Option rendering does not prove that every option branch is correct. Inventory drift must fail tests. No silent exception suppression or counting unsupported engine tests as passed. Real-world document fidelity, sustained capacity, physical cameras and all browser/OS combinations remain separate acceptance areas.

## Completion evidence

All ten final integrated stages passed. See [VERIFICATION.md](VERIFICATION.md) and [verification.json](verification.json) for counts, measured coverage, the PDF-to-image defect and remaining evidence boundaries.
