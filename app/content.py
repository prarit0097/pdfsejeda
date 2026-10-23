"""Original, task-focused help articles; no user documents or tracking data."""

GUIDES = {
    "compress-pdf-for-email": {
        "title": "How to compress a PDF for email",
        "description": "Choose PDF compression settings, check small text and keep a readable copy before emailing your document.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("compress-pdf", "Compress PDF"), ("split-pdf", "Split PDF")],
        "sections": [
            {
                "heading": "Start with the attachment limit",
                "paragraphs": [
                    "A PDF that looks simple can still contain large scanned images. Before changing it, check the attachment limit shown by your email service or the recipient's upload form. Leave some room for other attachments; a file just below the limit may still be awkward to send.",
                    "Keep the original document. Compression can reduce the detail in photographs and scanned text, so you need a copy to compare against if a smaller version becomes difficult to read.",
                ],
            },
            {
                "heading": "Make a balanced first attempt",
                "paragraphs": ["The compression tool lets you choose image quality and, under advanced options, the maximum image resolution. Start with Balanced quality and the recommended 144 dpi setting for a document mainly read on a screen."],
                "steps": [
                    "Open Compress PDF and upload the document.",
                    "Choose Balanced image quality. Keep colors if diagrams, stamps or highlighted sections depend on them.",
                    "Run compression and download the result.",
                    "Compare the file size and inspect the smallest text, signatures, photographs and any QR codes at a readable zoom.",
                ],
            },
            {
                "heading": "Adjust quality to the job",
                "paragraphs": [
                    "If the file remains too large, try Smaller file quality or a lower image resolution. A 72 dpi setting can be useful for a quick screen preview, but fine print may suffer. For a document someone will print, try 200 or 300 dpi and check the output before sending it.",
                    "Grayscale may help when color carries no meaning. Avoid it for charts that distinguish values by color or documents where the original ink color matters. Check both screen appearance and any printing requirement.",
                ],
            },
            {
                "heading": "When the size barely changes",
                "paragraphs": [
                    "Some PDFs already use efficient image compression or contain mostly text. A small reduction is normal in those cases; the tool may return the original when it cannot make a smaller file. Repeatedly compressing the same result is unlikely to recover much space and can damage image quality.",
                    "If the recipient accepts several attachments, split the original into sensible sections instead. Give each file a clear name and check that no pages are missing. Uploads are processed on the server; review the privacy page before using sensitive documents.",
                ],
            },
        ],
    },
    "add-signature-to-pdf": {
        "title": "How to add a signature to a PDF",
        "description": "Type, draw or upload a signature, compare transparent versions and place it once in the PDF editor.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("pdf-editor", "PDF editor")],
        "sections": [
            {
                "heading": "Choose how to create the signature",
                "paragraphs": [
                    "Open the PDF editor, upload your document and choose Sign. You can reuse a signature saved in this browser or create a new one. Type offers handwriting styles and ink colors; Draw works with a mouse, finger or pen. Upload Image uses an existing photo or scan, and Camera lets you photograph a signature with permission.",
                    "For a photographed signature, use a clear, evenly lit image. Keep the paper flat and avoid strong shadows. A cropped photo with enough space around the ink is easier to inspect than an entire desk or page.",
                ],
            },
            {
                "heading": "Compare the image versions",
                "paragraphs": [
                    "After uploading a signature image, compare Original, Transparent A and Transparent B. Transparent A attempts to separate the ink from photographed paper. Transparent B removes near-white areas while retaining darker paper. The checkerboard indicates transparency, not a pattern that will be printed.",
                    "Cleanup preserves the retained pixels' original color rather than turning the signature into a selected pen color. Compare thin strokes and loops before choosing a version. Difficult shadows or pale ink can still lose detail; choose Original or prepare a cleaner photograph if neither transparent result looks right.",
                ],
            },
            {
                "heading": "Place and adjust it",
                "paragraphs": ["Save the chosen version to arm placement. On a mouse or pen device, a preview follows the cursor so you can see what will be placed. Each selection places one signature."],
                "steps": [
                    "Move to the required page and click where the signature should go. On touch devices, tap the location.",
                    "Select the placed signature to move or resize it. Use its Rotate, Duplicate or Delete controls as needed.",
                    "To place another signature through Sign, choose it again. Press Escape to cancel a pending placement.",
                    "Apply changes, download the PDF and inspect the signature at a normal reading size.",
                ],
            },
            {
                "heading": "Understand storage and signing limits",
                "paragraphs": [
                    "Save signature stores a reusable image in this browser. Uncheck it when creating a signature you only want to use once, especially on a shared device. Removing a saved entry does not remove signatures already placed in a PDF.",
                    "This creates a visual signature image. It does not provide certificate-based identity verification or a signing audit trail. Check the recipient's requirements before relying on a visually signed PDF for a formal process.",
                ],
            },
        ],
    },
    "merge-pdfs-in-order": {
        "title": "How to merge PDFs in the right order",
        "description": "Combine PDF files, check document and page order, and review bookmarks and forms before sharing the result.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("merge-pdf", "Merge PDF"), ("organize-pdf", "Organize pages"), ("delete-pdf-pages", "Delete pages")],
        "sections": [
            {
                "heading": "Decide the reading order first",
                "paragraphs": [
                    "A merged PDF is easier to review when the documents follow a clear sequence: cover letter, main document, then supporting material, for example. Decide that sequence before uploading. File names such as 01-cover and 02-report can help you keep track, but always check the order shown in the tool.",
                    "Keep the source files until you have reviewed the final result. Two files with similar names may be different revisions, and a page count alone will not reveal that the wrong version was included.",
                ],
            },
            {
                "heading": "Combine the files",
                "paragraphs": ["Merge PDF appends the pages from each input in the order of its file list. Changing document order moves the whole document; rearranging individual pages is a separate job."],
                "steps": [
                    "Open Merge PDF and upload the files you want to combine.",
                    "Reorder the file list into the intended reading sequence. Remove duplicates and add any missing inputs.",
                    "Review the available merge options, then run the tool.",
                    "Download the PDF and check the first and last page of each original document at its new boundary.",
                ],
            },
            {
                "heading": "Choose options for your reader",
                "paragraphs": [
                    "Bookmarks help readers navigate longer documents. The merge options let you retain or discard existing bookmarks and choose document-based entries. A table of contents can be useful for a bundle, but check that its labels make sense rather than exposing unclear source file names.",
                    "For double-sided printing, inserting a blank page after an odd-length input can make the next document start on a new sheet. Leave that option off when continuous screen reading matters more. Mixed page sizes may be intentional, so inspect landscape sheets and drawings before choosing page-size normalization.",
                ],
            },
            {
                "heading": "Check more than the page count",
                "paragraphs": [
                    "Open the downloaded PDF and inspect page rotation, cropped edges and the transition between files. If you need to move a single page, use Organize pages on the result. Use Delete pages only after confirming which pages are genuinely unwanted.",
                    "If the inputs contain interactive forms, check their field values and behavior in the merged copy. Also check any existing digital signatures: editing or assembling a document can affect signature validation. Do not assume a merged copy preserves the verification status of its source files.",
                ],
            },
        ],
    },
    "make-scanned-pdf-searchable": {
        "title": "How to make a scanned PDF searchable",
        "description": "Use OCR to add searchable text to scanned PDFs, choose the document language and check recognition errors.",
        "published": "2026-10-22",
        "updated": "2026-10-23",
        "figure": {
            "src": "/static/img/ocr-searchable-text-2026-10-23.webp",
            "alt": "Illustration of a scanned page, a magnifying glass and the same page with a selectable text layer and search icon.",
            "caption": "OCR adds searchable text while keeping the scanned page appearance. Conceptual illustration created with AI assistance; not a product screenshot.",
            "width": 1774, "height": 887,
        },
        "related_tools": [("ocr-pdf", "OCR PDF"), ("deskew-pdf", "Deskew PDF"), ("pdf-to-word", "PDF to Word")],
        "sections": [
            {
                "heading": "Check whether the PDF needs OCR",
                "paragraphs": [
                    "Try selecting a sentence or searching for a word you can clearly see. If the page behaves like one large photograph, it may not contain a text layer. Optical character recognition, or OCR, reads those page images and adds machine-readable text so a PDF viewer can search and select it.",
                    "OCR does not rewrite the photographed page into a neatly typeset document. In this tool, searchable PDF output keeps the original page appearance and adds an invisible text layer. Plain text output is useful when you need the recognized words without the page layout.",
                ],
            },
            {
                "heading": "Prepare a readable scan",
                "paragraphs": [
                    "Recognition works best when characters are sharp, upright and evenly lit. If you can rescan the source, capture the whole page without cutting off margins or shrinking small print. A heavily compressed image may already have lost details that OCR cannot recover.",
                    "For pages tilted slightly by the scanner, Deskew PDF can help before recognition. Review its output first: fixing a small skew is different from correcting a distorted phone photograph. Use the clearest available source rather than repeatedly processing a poor copy.",
                ],
            },
            {
                "heading": "Run recognition and verify the result",
                "paragraphs": ["Choose the language used in the document from the languages available in the OCR tool. The correct language helps with vocabulary and character recognition; it does not guarantee an accurate transcription."],
                "steps": [
                    "Open OCR PDF and upload the scanned document.",
                    "Select the appropriate available language and choose the output: Searchable PDF or Text file.",
                    "Run OCR, then download and open the result.",
                    "Search for a distinctive phrase and copy a sample paragraph into a text editor. Compare it with the visible scan.",
                ],
            },
            {
                "heading": "A search hit is only the first check",
                "paragraphs": ["Finding a heading does not prove the scanned body was recognized. Check a copy of the downloaded output before relying on its text."],
                "steps": [
                    "Search for a distinctive phrase from the middle of the page, not only its heading. Repeat on a page with a different layout.",
                    "Copy a name, a date and a total into a plain-text editor. Compare each character with the scan. Watch for O versus 0, l versus 1, missing decimal points and lost minus signs.",
                    "Copy a paragraph from a two-column page. Check that the pasted lines follow the intended column order.",
                ],
            },
            {
                "heading": "When running OCR again does not help",
                "paragraphs": ["The tool leaves pages that already have selectable text unchanged. An existing heading or an inaccurate older text layer can therefore leave a scanned body unrecognized. Re-running the same PDF is not a guaranteed repair. Keep the original scan and review the result; the current interface has no force-recognition control."],
            },
            {
                "heading": "Review names, numbers and complex layouts",
                "paragraphs": [
                    "Check names, dates, account numbers and totals individually. Similar characters such as 0 and O, or 1 and l, can be confused even when the page looks clear. Columns, stamps, tables and handwriting need extra attention; text extraction may not follow the intended reading order.",
                    "If you plan to convert the scan to Word, OCR can provide a useful text layer first, but you should still expect to review the resulting layout. Keep the original scan alongside the output when exact wording matters, and avoid treating unreviewed OCR text as an authoritative record.",
                ],
            },
        ],
    },
    "fill-and-flatten-pdf-forms": {
        "title": "How to fill a PDF form and save a finished copy",
        "description": "Fill interactive PDF fields or add text to a flat form, then decide whether to keep the fields editable or flatten a finished copy.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("pdf-editor", "PDF editor"), ("pdf-forms", "PDF forms"), ("flatten-pdf", "Flatten PDF")],
        "sections": [
            {
                "heading": "First check what kind of form you have",
                "paragraphs": [
                    "Click inside a box where an answer belongs. An interactive PDF form lets you type into its existing fields or choose a checkbox or dropdown. A scanned or flat form may only show the printed outlines. It needs text placed over the page, or new form fields if someone else should fill it in later.",
                    "These choices produce different results. A Text object adds an answer you can position on the page. A Text field creates a box that a PDF reader can fill later. Use Text for a one-off answer on a flat form; use the field tools when preparing a reusable form.",
                ],
            },
            {
                "heading": "Complete the answers before changing the format",
                "paragraphs": ["Keep an untouched copy of the form. Then open the PDF editor and upload the version you want to complete. Final processing runs on the hosting server, so check the privacy information before uploading personal or confidential material."],
                "steps": [
                    "Fill the existing text fields, checkboxes and dropdowns directly on the page.",
                    "If the form is flat, choose Text and place each answer in its printed space. Adjust size and position so it remains legible without covering the question.",
                    "Review long answers, dates, names and every selected option. Check whether a field has hidden text that does not fit in its visible box.",
                    "Choose whether to keep the form editable, then select Apply changes and download the result.",
                ],
            },
            {
                "heading": "Keep an editable copy when revisions are likely",
                "paragraphs": [
                    "Leave Flatten form fields when saving unchecked if the recipient needs to change field values. Open the downloaded file in the PDF reader they are likely to use and confirm that the fields and values work there. A browser preview alone is not a check of another reader's form behavior.",
                    "For a completed copy whose answers should become ordinary page content, select Flatten form fields when saving. Keep the editable source separately. If you already downloaded the filled form, Flatten PDF also offers Only form fields; this differs from Everything, which turns full pages into images and can affect text selection and file size.",
                ],
            },
            {
                "heading": "Flattening is a format choice, not a security guarantee",
                "paragraphs": [
                    "Flattening removes the normal form-field interaction from that copy. It does not make the document tamper-proof or certify who completed it. A recipient with editing software can still alter page content.",
                    "It also does not redact sensitive information. Whiteout and visual text replacement in this editor cover content without securely removing the original text. For information that must be removed before sharing, use a dedicated redaction process and verify the result. Review the downloaded PDF, rather than relying on how the editor looked before saving.",
                ],
            },
        ],
    },
    "extract-pdf-pages-for-sharing": {
        "title": "How to extract selected pages from a PDF",
        "description": "Create a PDF containing just the pages you need, account for cover pages and printed numbering, and check the extracted copy before sharing.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("extract-pdf-pages", "Extract pages"), ("organize-pdf", "Organize pages"), ("edit-pdf-metadata", "Edit PDF metadata")],
        "sections": [
            {
                "heading": "Count PDF pages, not the numbers printed on them",
                "paragraphs": [
                    "A report may have a cover and a contents page before its printed page 1. In that file, the sheet labelled 1 is the third PDF page. Page selection uses the position in the uploaded PDF, starting at 1; it does not read the number printed in a header or footer.",
                    "For example, suppose a 12-page file has two introductory pages and you need printed pages 3 through 5. Check the thumbnails: those may be PDF pages 5 through 7. Confirm the first and last sheet by their content before entering the range.",
                ],
            },
            {
                "heading": "Make a separate copy of the pages you need",
                "paragraphs": ["Extract pages creates an output containing selected pages. This is useful when someone needs one section of a longer document. Keep the original until you have checked the new copy."],
                "steps": [
                    "Open Extract pages and upload the source PDF.",
                    "Select the required thumbnails or enter a page selection such as 2-4,7 for PDF pages 2, 3, 4 and 7.",
                    "Run the tool and download the extracted PDF.",
                    "Open the download and check its page count, first and last page, orientation and any page with important small print.",
                ],
            },
            {
                "heading": "Choose extraction, splitting or reordering deliberately",
                "paragraphs": [
                    "Use extraction when you want selected pages together in a new document. Splitting is useful when you want several separate files, such as one file per section. Organize pages is the better choice when you need to rearrange the extracted sheets into a different reading sequence.",
                    "Do not assume a selection typed in an unusual sequence will create that reading order. Use Organize pages to set the final sequence explicitly and check its downloaded output. Clear file names also help: include the section name or date rather than leaving several copies called document.pdf.",
                ],
            },
            {
                "heading": "Check context and sensitive details before sharing",
                "paragraphs": [
                    "A short extract can lose its meaning when the definitions, footnotes or continuation page are missing. Include enough context for the recipient to understand the section. Review bookmarks and links that may have referred to pages outside the selection, and test any form fields you expect the recipient to use.",
                    "Extracting pages is not a document-sanitization or redaction process. Information in the retained pages, annotations or metadata may still be present. Review document properties with Edit PDF metadata when needed; removing metadata alone is not a complete privacy check. Uploads are sent to the server for processing, so read the privacy information before using sensitive source files.",
                ],
            },
        ],
    },
    "convert-pdf-to-word-with-layout-checks": {
        "title": "How to convert a PDF to Word and check the layout",
        "description": "Turn PDF text into an editable Word document, recognize when a scan needs OCR, and review tables, reading order and page breaks after conversion.",
        "published": "2026-10-22",
        "updated": "2026-10-22",
        "related_tools": [("pdf-to-word", "PDF to Word"), ("ocr-pdf", "OCR PDF"), ("extract-text-from-pdf", "PDF to text")],
        "sections": [
            {
                "heading": "Check the source before converting it",
                "paragraphs": [
                    "If the original Word document is available, edit that version first. A PDF describes where content appears on a page; it may not retain the paragraph, table and section structure that made the original easy to edit. Conversion has to reconstruct that structure from the information left in the PDF.",
                    "Try selecting and copying a short paragraph from the PDF. If it is only a page photograph, use OCR to create a searchable text layer before trying a text-based conversion. If copied words come out in the wrong order or with missing characters, expect to correct them after conversion too.",
                ],
            },
            {
                "heading": "Create the Word copy",
                "paragraphs": ["Prarit Sidana PDF produces a DOCX document by reconstructing text, headings, tables and pictures. It is a starting point for editing; complex layouts and fonts can differ from the PDF. Processing happens on the server, so review the privacy information before uploading confidential work."],
                "steps": [
                    "Open PDF to Word and upload your PDF. Keep the original for comparison.",
                    "Run the conversion and download the DOCX result.",
                    "Open the DOCX in your word processor alongside the PDF.",
                    "Check the document's wording and structure before spending time adjusting its appearance.",
                ],
            },
            {
                "heading": "Review the places where layout errors hide",
                "paragraphs": [
                    "Start with reading order: a two-column page can be difficult to reconstruct, and a caption may sit between unrelated paragraphs. Read across each column, then check headings, lists and repeated headers. Fix paragraph structure before using spaces or blank lines to force the page to look right.",
                    "Compare tables cell by cell. Confirm that headings match their columns, wrapped rows have not split into separate records, and totals, decimal points and minus signs are correct. If the goal is to work with table data rather than prose, a spreadsheet conversion may be more suitable, but that output needs its own review.",
                    "Check images and captions together, then look at page breaks, footnotes and small print. Font substitution can move a line onto the next page. After editing, review the exported PDF again if that is what you will ultimately send.",
                ],
            },
            {
                "heading": "Choose a simpler output when layout is unnecessary",
                "paragraphs": [
                    "If you only need the words for notes or a quotation, PDF to text can avoid the extra work of repairing a Word layout. Compare any quotation with the original, especially when OCR was involved. Names, dates and numbers deserve a separate check.",
                    "Avoid treating conversion as proof that every element survived. Keep the source PDF and check the finished document at a normal reading size. A readable, correctly ordered copy is more useful than one that only resembles the source in a quick thumbnail preview.",
                ],
            },
        ],
    },
}
