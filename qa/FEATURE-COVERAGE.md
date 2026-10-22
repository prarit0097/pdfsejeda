# Feature-to-test map

The per-tool matrix is in [TEST-PLAN.md](TEST-PLAN.md). Canonical scenario
coverage is enforced by `test_canonical_tool_inventory_has_exactly_one_scenario`.
A newly registered tool without a scenario fails the pool.

| Feature area | Executable tests | Acceptance evidence |
|---|---|---|
| All 51 public pages, assets, links, errors | `tests/test_page_contracts.py`; `scripts/tool_ui_regression.py` | Actual HTML, all local assets and navigation routes; desktop/mobile shells |
| All 160 declared options | `tests/test_page_contracts.py`; `scripts/tool_ui_regression.py` | Form controls, defaults, enum choices, bounds, conditional declarations; actual control changes at desktop/mobile sizes |
| All 43 tools | `tests/test_tool_catalogue.py`; `qa/tool_scenarios.py`; `scripts/tool_ui_regression.py` | Real uploaded generated documents, task lifecycle, signed download, parsed semantic output and UI submission |
| Organize/split/extract/mix | `tests/test_organize.py`, `test_mix_parity.py`; existing browser suite | Page order/counts/rotations, bookmarks, exhaustion, independent per-source options and invalid ranges |
| Crop/layout/optimization | `tests/test_modify.py`, `test_crop_scopes.py` | Dimensions/scopes, color/image operations, crop edge cases, image reduction and raster output |
| Stamps/security/document settings | `tests/test_modify.py`, `tests/test_tool_catalogue.py` | Text tokens, metadata, bookmarks, annotation removal, encryption/password/decryption |
| Conversions/engines | `tests/test_convert.py`, tool catalogue; optional live smoke | Parsed Office tables/slides, images/text, real LibreOffice/OCR/Chromium, engine-failure fallback distinctions |
| API input/output contracts | `tests/test_api.py`, `test_api_contracts.py` | Multipart/chunk retries, malformed input, wrong types, missing resources, PDF byte ranges, active-content download restrictions |
| SSRF/signatures/expiry/queue | `tests/test_core.py`, `test_api.py`, `test_pdfium_threading.py` | Pinned public fetches and redirects, capability entropy, expiry, cancellation/admission/timeout, native render locking |
| Editor and advanced forms | `tests/test_editor.py`, `test_editor_extra.py`, `test_forms_advanced.py`; `scripts/editor_regression.py` | Text/objects/page order/rotation/blank pages, field values and appearances, undo/find-replace/draft recovery, mobile touch and saved PDFs |
| Local signatures | `scripts/signature_regression.py`, `signature_cleanup_regression.py` | Fonts/drawing/image/camera, saved library, actions, hover cursor preview, one-time placement, original RGB and PNG/PDF alpha |
| Shared UI | `scripts/shared_feature_regression.py`; existing browser suite | Categories/search/theme, uploads/remove/reset, URL rejection, selection validation, workflow import/export/rename/chain/delete |
| Results and chaining | API and browser/editor suites | Polling, signed download, ZIP items, preview, result redirect/expiry, continue and workflows |
| Bounded concurrency | `scripts/concurrency_regression.py`; queue/native-lock unit tests | Sixteen simultaneous real output tasks; not sustained capacity certification |
| Automation | `scripts/run_test_pool.py`; `.github/workflows/test-pool.yml` | Isolated server/data, bounded stages, JSON/JUnit/branch coverage and CI artifacts |

Rendering/changing an option is a control contract, **not** an assertion that all
semantic branches or arbitrary option combinations have been verified. The
measured Python coverage and remaining limitations belong in VERIFICATION.md.
Physical cameras, non-Chromium browsers, real-world arbitrary-document fidelity
and sustained production load require separate acceptance work. The deferred
account/billing/cloud/email-signing features are outside this pool's scope.
