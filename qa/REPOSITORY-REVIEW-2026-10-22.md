# Repository and handover review — 2026-10-22

Reviewed baseline: `9e6b3d6` on `main`. The working tree was clean before this review.

## Assessment

The repository implements a substantial PDF toolkit, rather than only page shells.
The guide's core description agrees with the inspected code: FastAPI/Jinja2,
43 canonical tools, a shared browser editor, server-side document processing,
local browser workflows and a bounded in-process thread queue. It is suitable
for the documented single-process deployment model; this review does not
establish production capacity, arbitrary-document fidelity or full Sejda parity.

## Architecture and strengths

- `app/main.py` assembles middleware, routes and expiry cleanup. `app/web.py`
  renders pages; `app/api.py` implements upload → task → polling → download.
- `app/tools/registry.py` centralizes tool metadata and generic page options.
  Organize, modify, stamp, security, conversion and editor modules supply handlers.
- `app/jobs.py` bounds worker/queue admission and tracks task state in memory;
  `app/storage.py` stores bytes and atomic metadata on disk. Restarting loses
  task records. Multiple Uvicorn processes would require shared job state.
- `app/security.py` validates public destinations and pins outbound connections
  to resolved IPs. Signed downloads, random capability IDs, body limits,
  safe serving and TTL checks provide useful explicit boundaries.
- PDFium calls use a shared lock. This protects a native engine that cannot
  safely run concurrently, but also serializes PDFium-heavy processing.
- Tests include semantic output inspection, API/page contracts and separate
  browser/editor/signature/concurrency scripts. CI installs conversion engines;
  its configuration alone is not a successful hosted run.
- Vendored PDF.js/signature assets retain manifests and license notices. No
  dependency vulnerability scan or comprehensive license audit was performed.

## Prioritized follow-ups

1. **High — bound Flatten rendering allocations.** `app/tools/modify.py:622`
   converts client `resolution` directly to an integer; `_rasterize` at line 649
   passes `dpi / 72` to `page.render` without a DPI or page-pixel ceiling.
   `Tool.validate` checks input count/type, not these numeric options. A direct
   API caller can bypass the UI's radio choices; large page dimensions are
   another allocation multiplier. PDF-to-image already clamps DPI and applies
   `_safe_dpi` in `app/tools/convert.py`. Reuse a common finite/positive DPI and
   pixel-budget policy, and test rejection/downscaling without allocating huge
   images. The missing bound is confirmed by source inspection; no OOM or
   production exploit was attempted.
2. **High — bound aggregate upload/storage use.** Task quota is consumed at task
   creation, while upload/chunk/import and result continuation can create disk
   data without consuming that quota. Per-file caps and TTL do not cap the
   total retained bytes. Add storage budgets/admission and explicit overload
   responses. The existing guide already acknowledges no aggregate disk quota.
   This review did not fill the disk or run an abuse/load experiment.
3. **Medium — move synchronous upload/continuation work off the event loop.**
   `app/api.py:79` opens PDFs to inspect metadata; async upload routes invoke it
   directly. Chunk writes and `continue_with` file copies also run synchronously.
   On the required single Uvicorn process, slow disk/parser work can delay
   unrelated requests even when the processing queue has free capacity.
   Use bounded thread offloading and measure simultaneous upload/poll latency.
   This is a source-based concurrency risk; latency was not benchmarked here.
4. **Medium — harden worker lifecycle before increasing scale.** Cooperative
   cancellation cannot terminate a stuck native call. A hung PDFium operation
   retains the shared lock; worker cleanup also waits on that lock. The app
   lifespan cancels its sweeper but does not invoke `queue.shutdown()` or await
   sweeper cancellation. Add explicit lifecycle handling and consider killable
   worker processes when hard deadlines become a requirement. Shutdown hangs
   were not reproduced in this pass.

Maintainability: conversion and editor modules concentrate substantial behavior.
Prefer extracting shared rendering/validation primitives when addressing the
items above, followed by bounded feature-based separation. A framework rewrite
is not justified by the inspected evidence. Python coverage reported by the
earlier full pool is incomplete; browser JavaScript is not instrumented by it.

## Analysis of sejedarules.md

The guide is a useful current-state handover: it explains scope, routes, storage,
coordinate systems, optional engines, security, deployment and known limits.
Its separation of implementation, dated evidence and owner-deferred work is
particularly valuable. Accounts/billing, cloud integrations, email signing and
Google/Bing owner-account setup remain deliberately deferred.

The 43-tool and 56-public-page inventories are covered by the passing Python
contracts. The task alphabet has 32 symbols, giving the documented 160 random
bits across 32 positions. The deployed application revision and hosted CI status
remain historical records; this pass did not inspect the server or hosted CI.

Two stale plan descriptions were corrected: the phase-1 task-ID length still
said eight characters, and the optional-engine table mentioned OCRmyPDF although
the implementation/image uses Tesseract directly. Follow-ups above are now
listed in the guide and plan without treating them as implemented fixes.

## Fresh validation and publication limits

- **Passed:** `.venv/Scripts/python.exe -m pytest tests -q --tb=short` —
  **663 passed, zero failures/skips, two warnings, 64.15 seconds**. Warnings:
  Starlette TestClient's HTTPX deprecation and Pillow `Image.getdata` deprecation.
- **Passed:** `.venv/Scripts/python.exe -m pip check` — no broken requirements.
- **Passed:** `git diff --check` after documentation edits.
- **Not run:** full staged pool, fresh browser/mobile/camera tests, conversion
  engine smoke, production checks, hosted CI inspection, capacity/abuse tests,
  vulnerability scan and exhaustive document/option-combination validation.
- Scope of changes: this report, handover and plan documentation only. No
  application changes, deployment, service restart or search submission.
  Previously recorded application image revision remains `dee688f`; its current
  live health was not verified. Follow-up fixes require separate implementation
  and validation work.
