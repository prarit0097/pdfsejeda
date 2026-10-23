# Focused OCR guide revision — 2026-10-23

**Status:** proposed addition to the existing
[scanned-PDF guide](https://pdf.praritsidana.com/guides/make-scanned-pdf-searchable).
No new article URL, deployment or publication by this workstream. This replaces
the earlier idea for a separate OCR article, which would overlap existing copy.

## Proposed section: A search hit is only the first check

A successful search means the viewer found text; it does not prove every word
was recognized correctly. Try this quick check on a copy of the downloaded PDF:

1. Search for a distinctive phrase from the middle of the page, not only its
   heading. Repeat on a page with a different layout.
2. Copy a name, a date and a total into a plain-text editor. Compare each
   character with the visible scan. Watch for `O` versus `0`, `l` versus `1`,
   missing decimal points and lost minus signs.
3. Copy a paragraph from a two-column page. Read the pasted text to check that
   lines follow the intended column order.

Searchable is different from editable. OCR adds a text layer while retaining
the scanned page appearance; it does not rebuild the page as Word paragraphs.
If you need to revise the wording, convert a checked copy to Word, then review
its text, tables and layout again.

## Proposed illustration caption and alt text

**Caption:** A scan, a searchable PDF and an editable document serve different
jobs. Check the recognized words before using them in another format.

**Suggested alt text, subject to inspecting the finished artwork:** Diagram
comparing a scanned page, a searchable PDF with a text layer, and an editable
document, with a reminder to check recognized text.

The parent workstream must adjust the alt text to the actual artwork and record
its provenance. This workstream created no image.

## Editorial evidence and integration notes

- Source: `app/content.py`, existing `make-scanned-pdf-searchable` guide already
  covers OCR basics, language selection, scans, search/copy checks and conversion
  limits. Add the compact checklist there; avoid duplicating its introductory
  sections or creating another page for the same search intent.
- Source: `app/tools/convert.py`, `ocr()` uses Tesseract's `textonly_pdf=1` output
  and overlays that text layer on the original page. Its UI exposes Searchable
  PDF or Text file; do not imply the visible radio control selects both together.
- Source: `app/tools/convert.py`, `_has_text()` considers a page with at least 20
  non-whitespace characters already textual and skips OCR for that page. A
  scanned body with an existing heading or an inaccurate earlier text layer may
  therefore be skipped. Re-running OCR is not a promised repair for that case;
  there is no exposed force-OCR setting. This technical edge case belongs in
  troubleshooting if expanded later, not as an unsupported workaround.
- Useful existing links: [OCR PDF](https://pdf.praritsidana.com/ocr-pdf) for the
  task, [PDF-to-Word checks](https://pdf.praritsidana.com/guides/convert-pdf-to-word-with-layout-checks)
  for the editable-copy step. Preserve the guide's privacy/server-processing
  note and related Deskew PDF link.
- Validation: implementation and existing copy inspected; no code, app content,
  image, browser state or publication changed. No tests run for this Markdown
  draft. Parent owns source integration, central handover and final validation.
