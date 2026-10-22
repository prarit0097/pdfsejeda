# Third-party assets

PDF.js 6.4.299 (`pdfjs-dist`) is vendored under `app/static/vendor/pdfjs` from
https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz.
Its Apache-2.0 license is retained in `app/static/vendor/pdfjs/LICENSE`.
Additional font/codec notices shipped in the package remain in their asset folders.
`manifest.json` records the archive SHA-256 and each selected file's SHA-256.

The selected package includes the ES module renderer and worker, CMaps, standard
fonts, and WASM codecs. These are Mozilla PDF.js assets, not Sejda application code.
To upgrade, obtain a pinned official npm package, retain its notices, regenerate
the manifest, and rerun the editor and browser regressions.

Python dependency versions are listed in `requirements.txt`. Optional runtime
engines are LibreOffice, Tesseract and Playwright Chromium. This notice records
asset provenance; it is not a completed audit of every transitive dependency.


Signature fonts are self-hosted under `app/static/vendor/signature-fonts`:
Dancing Script, Caveat, Homemade Apple, Sacramento, Allura, Great Vibes, Pacifico,
Satisfy, Shadows Into Light, Marck Script, Parisienne and Yellowtail. The font
binaries come from the official Google Fonts service; each corresponding
SIL Open Font License or Apache-2.0 text is retained as `*-LICENSE.txt`.
The directory's `manifest.json` records family names, official download/licence
URLs and SHA-256 hashes. Upstream: https://github.com/google/fonts.
Do not remove these licences or relabel the original font family names.
