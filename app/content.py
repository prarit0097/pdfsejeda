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
        "updated": "2026-10-22",
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
                    "Select the appropriate available language and the output formats you need: searchable PDF, text, or both.",
                    "Run OCR, then download and open the result.",
                    "Search for a distinctive phrase and copy a sample paragraph into a text editor. Compare it with the visible scan.",
                ],
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
}
