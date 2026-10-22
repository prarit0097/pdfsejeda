/* Pinned, self-hosted PDF.js. No document is sent to an external preview service. */
import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
window.pdfjsLib = pdfjsLib;
