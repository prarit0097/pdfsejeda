# Full-pool verification - 2026-10-22

Status: **eleven stage types passed after a targeted mobile harness retry** on Windows 11 / Python 3.13.5. The initial full attempt failed its mobile stage; that evidence is retained.
Commands: `python scripts/run_test_pool.py --include-network`, then `python scripts/run_test_pool.py --stage all-tool-ui-mobile`.
Machine-readable summary: [verification.json](verification.json).

| Layer | Result |
|---|---|
| Python semantic/API/contracts | **663 passed, 0 failures, 0 skips**, two existing deprecation warnings (previous verified pool: 576) |
| Canonical tool semantic HTTP scenarios | **43/43**; generated upload, real task/poll/signed download and parsed output |
| Desktop tool UI | **43/43 submissions**, all **160/160** declared controls interacted with |
| Mobile tool UI | **43/43 submissions**, all **160/160** declared controls interacted with; native touch form creation |
| Public page shells | **56/56** at mobile size; page/asset/link/contracts also verified in Python |
| Existing Chromium regression | **63/63** |
| Shared feature groups | **5/5** |
| Editor/recovery/forms/workflow/touch groups | **8/8** |
| Signature groups | **4/4** |
| Signature cleanup/colour/placement checks | **10/10** |
| Concurrent real PDF tasks | **16/16** |
| Live HTTP/network smoke | **58/58**, including public URL import, HTML printing, real LibreOffice and OCR |
| Dependency consistency | `pip check` passed |

These layers overlap; their counts are not added into an inflated unique-test total.
Each all-tool UI run reports 99 checks: 43 submissions plus 56 page-shell checks. The dedicated SEO stage verifies 56 canonical pages and eight responsive layouts; 82 new SEO contracts are included in the Python count.

## Harness correction in this release

The first mobile Split by text test calculated drag coordinates from a fresh canvas's default 300x150 dimensions before PDF.js assigned the real page dimensions. Its selected area therefore contained no fixture text. The test now waits for the assigned CSS width before calculating pointer coordinates. The entire mobile stage then passed: 99/99 UI/page checks and 160/160 controls. No application processing change was needed for this failure.

## Previous application defect, still covered

The PDF-to-JPG/PNG page advertised blank Pages as "all pages", but the shared
selection validator blocked submission until a page was selected. The validator
now requires a selection only for Extract pages and Delete pages. PDF-to-image
with blank Pages successfully produces all three fixture images through the UI;
extract/delete empty-selection validation remains tested. Page UI cache version
was incremented so deployed browsers fetch the fix.

Initial test-harness corrections included clicking visible custom radio labels,
choosing UI-exposed crop units, scrolling the area canvas below the fixed header,
and placing mobile form drags above the fixed footer. These were harness fixes,
not additional claimed application defects. Image extraction correctly deduplicates
a repeated embedded image; its expected fixture count was corrected accordingly.

## Measured coverage and limits

Python statement coverage: **79.17%** (4153/5246 statements).
Python branch coverage: **65.30%** (1272/1948 branches).
The combined coverage metric is 75.41%. This measures the Python unit/API process;
it does not instrument browser JavaScript or separate live-server processes.
Uncovered error/fallback/option paths remain; control interaction coverage does
not prove every semantic option branch or every combination is correct.

Fixtures are generated. This pool does not certify arbitrary real-world document
fidelity, sustained production capacity, physical cameras, other browsers/OSes,
or deliberately excluded accounts/billing/cloud/email signing. Camera tests use
a synthetic local stream. Current-release Ubuntu CI is [in progress](https://github.com/prarit0097/pdfsejeda/actions/runs/39826361415); it was still installing conversion engines when observed, so its success is not claimed. The preceding release's [hosted run succeeded](https://github.com/prarit0097/pdfsejeda/actions/runs/39821720115); that result is not attributed to this release.

Initial run: `data-qa-pool/runs/20261022T174617484976Z/`. Targeted mobile retry: `data-qa-pool/runs/20261022T175222139964Z/` (ignored), with logs,
JUnit XML, coverage JSON and per-viewport inventories. Only the compact summary
and source checksums are committed. No private PDFs/photos or credentials are
part of the fixtures or committed evidence.

## Public release verification

Implementation `dee688f` deployed to https://pdf.praritsidana.com with the domain-aligned Prarit Sidana PDF brand. Public read-only SEO verification passed for all 56 sitemap URLs and eight responsive branding/layout checks. Metadata, canonicals and JSON-LD matched; private API pages remain noindex. The exhaustive pool ran only on local isolated servers. Container healthy, no OOM; all 15 existing container identities and 19 host status/redirect responses matched baseline. Image identity is in verification.json. Search notification evidence is separate in marketing/SEO-STATUS.md; no indexing or ranking claim is made.
