# Full-pool verification ? 2026-10-22

Status: **all ten integrated stages passed** on Windows 11 / Python 3.13.5.
Command: `python scripts/run_test_pool.py --include-network`.
Machine-readable summary: [verification.json](verification.json).

| Layer | Result |
|---|---|
| Python semantic/API/contracts | **576 passed, 0 failures, 0 skips**, two existing deprecation warnings (previous pool: 170) |
| Canonical tool semantic HTTP scenarios | **43/43**; generated upload, real task/poll/signed download and parsed output |
| Desktop tool UI | **43/43 submissions**, all **160/160** declared controls interacted with |
| Mobile tool UI | **43/43 submissions**, all **160/160** declared controls interacted with; native touch form creation |
| Public page shells | **51/51** at mobile size; page/asset/link/contracts also verified in Python |
| Existing Chromium regression | **63/63** |
| Shared feature groups | **5/5** |
| Editor/recovery/forms/workflow/touch groups | **8/8** |
| Signature groups | **4/4** |
| Signature cleanup/colour/placement checks | **10/10** |
| Concurrent real PDF tasks | **16/16** |
| Live HTTP/network smoke | **58/58**, including public URL import, HTML printing, real LibreOffice and OCR |
| Dependency consistency | `pip check` passed |

These layers overlap; their counts are not added into an inflated unique-test total.
Each all-tool UI run reports 94 checks: 43 submissions plus 51 page-shell checks.

## Application defect found and fixed

The PDF-to-JPG/PNG page advertised blank Pages as ?all pages?, but the shared
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

Python statement coverage: **78.82%** (4067/5160 statements).
Python branch coverage: **64.86%** (1248/1924 branches).
The combined coverage metric is 75.03%. This measures the Python unit/API process;
it does not instrument browser JavaScript or separate live-server processes.
Uncovered error/fallback/option paths remain; control interaction coverage does
not prove every semantic option branch or every combination is correct.

Fixtures are generated. This pool does not certify arbitrary real-world document
fidelity, sustained production capacity, physical cameras, other browsers/OSes,
or deliberately excluded accounts/billing/cloud/email signing. Camera tests use
a synthetic local stream. Hosted Ubuntu CI is configured; no hosted CI success
is claimed in this record.

Raw run: `data-qa-pool/runs/20261022T171214729720Z/` (ignored), with logs,
JUnit XML, coverage JSON and per-viewport inventories. Only the compact summary
and source checksums are committed. No private PDFs/photos or credentials are
part of the fixtures or committed evidence.

## Public release verification

Implementation `d74893f` deployed to https://pdf.praritsidana.com. Bounded desktop
and mobile PDF-to-image submissions with blank Pages both passed, each producing
all three generated PNG images. The exhaustive pool was not run on production.
Container healthy, no OOM; all 15 existing container identities and 19 host
status/redirect responses matched baseline. Image identity is in verification.json.
