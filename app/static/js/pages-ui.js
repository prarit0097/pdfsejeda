/* Page thumbnails rendered with PDF.js, in one of these modes (tool.page_ui):
 *   select   — click pages to choose them; syncs the "pages" field (extract, delete)
 *   rotate   — rotate single pages              -> pageRotationsPerSource ["file:page:deg"]
 *   organize — reorder / rotate / duplicate / delete / add blank pages across files -> filePages ["file:page:rot"]
 *   split    — click between pages to set cut marks -> splitMode=after, pages "3,7"
 *   area     — draw a rectangle on page 1       -> area {x,y,width,height} (PDF points, top-left origin)
 */
(() => {
  const root = document.getElementById("pages-ui");
  if (!root || !window.Tool) return;
  const { icon, compressRanges, esc } = window.UI;
  const Tool = window.Tool, mode = root.dataset.mode;
  const docs = new Map();          // fileId -> Promise<PDFDocumentProxy>
  let cropAreas = {}, cropPage = 1, cropFileId = null;
  let items = [];                  // organize/rotate: {key, fileIdx, page, rot, deleted, blank}
  let selected = new Set();        // select mode: page numbers
  let cuts = new Set();            // split mode: split after page n
  let area = null;                 // area mode
  let lastClicked = null;          // select mode: anchor for shift-click ranges
  let thumbW = 130;

  function lib() {
    const l = window.pdfjsLib;
    if (l && !l.GlobalWorkerOptions.workerSrc) l.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
    return l;
  }

  function loadDoc(file) {
    if (!docs.has(file.id)) {
      docs.set(file.id, new Promise((resolve, reject) => {
        const go = () => lib() ? lib().getDocument({ url: `/api/files/${file.id}/view`, password: file.password || undefined,
          isEvalSupported: false, cMapUrl: "/static/vendor/pdfjs/cmaps/", cMapPacked: true,
          standardFontDataUrl: "/static/vendor/pdfjs/standard_fonts/", wasmUrl: "/static/vendor/pdfjs/wasm/"
        }).promise.then(resolve, reject) : setTimeout(go, 100);
        go();
      }));
    }
    return docs.get(file.id);
  }

  const observer = new IntersectionObserver(entries => {
    entries.forEach(en => { if (en.isIntersecting) { observer.unobserve(en.target); drawThumb(en.target); } });
  }, { root: null, rootMargin: "300px" });

  async function drawThumb(el) {
    const file = Tool.readyFiles()[+el.dataset.file];
    if (!file || el.dataset.blank) return;
    if (isImage(file)) {  // images (merge/organize) are one page each; show the picture itself
      const c = el.querySelector("canvas"), img = new Image();
      img.alt = ""; img.src = `/api/files/${file.id}/view`; img.className = "thumb-img";
      img.style.cssText = `max-width:100%;max-height:100%;transform:${c.style.transform}`;
      c.replaceWith(img);
      return;
    }
    try {
      const doc = await loadDoc(file);
      const page = await doc.getPage(+el.dataset.page);
      const vp1 = page.getViewport({ scale: 1 });
      const scale = (160 * (window.devicePixelRatio || 1)) / Math.max(vp1.width, vp1.height);
      const vp = page.getViewport({ scale });
      const c = el.querySelector("canvas");
      c.width = vp.width; c.height = vp.height;
      await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
    } catch (e) { /* password or damaged file: leave the grey sheet */ }
  }

  // Thumbnails index files by their position in Tool.readyFiles(), which is also the order of
  // `files[]` in the task body, so fileIdx in filePages / pageRotationsPerSource matches the server.
  function isImage(f) { return !f.pages && !/\.pdf$/i.test(f.name); }
  function pageCount(f) { return f.pages || (isImage(f) ? 1 : 0); }
  function pdfFiles() { return Tool.readyFiles().filter(f => f.pages); }

  function toolbar(html) {
    return `<div class="thumbs-toolbar">${html}<span style="flex:1"></span>
      <label class="muted small" style="display:flex;align-items:center;gap:8px">Zoom <input type="range" min="90" max="260" value="${thumbW}" data-zoom style="width:110px"></label></div>`;
  }

  function thumbHtml({ fileIdx, page, label, rot = 0, cls = "", tools = "", blank = false, key = "" }) {
    return `<div class="thumb ${cls}" data-file="${fileIdx}" data-page="${page}" data-key="${key}" ${blank ? 'data-blank="1"' : ""} tabindex="0">
      <div class="sheet"><span class="check-mark">${icon("check")}</span><canvas style="transform:rotate(${rot}deg)"></canvas>${tools ? `<div class="tools">${tools}</div>` : ""}</div>
      <span class="lbl">${esc(label)}</span></div>`;
  }

  function mount(html) {
    root.innerHTML = html;
    root.style.setProperty("--thumb", thumbW + "px");
    root.querySelectorAll(".thumb").forEach(t => observer.observe(t));
  }

  // ---------------- build per mode ----------------
  function build() {
    const files = pdfFiles();
    if (!files.length && !(mode === "organize" && Tool.readyFiles().some(isImage))) { root.innerHTML = ""; return; }
    if (mode === "metadata") return prefillMetadata(files[0]);
    if (mode === "bookmarks") return prefillBookmarks(files[0]);
    if (mode === "crop") {
      const want = document.querySelector('input[name="cropMode"]:checked')?.value === "area";
      if (!want) { root.innerHTML = ""; area = null; return; }
      if (cropFileId !== files[0].id) { cropAreas = {}; cropPage = 1; area = null; cropFileId = files[0].id; root.innerHTML = ""; }
      if (!root.querySelector(".area-wrap")) buildArea(files[0], "Draw the area to keep. Unmarked individual pages keep their original size.");
      return;
    }
    if (mode === "area") return buildArea(files[0]);
    if (mode === "select" || mode === "split") return buildSingle(files);
    if (mode === "rotate" || mode === "organize") return buildMulti(Tool.readyFiles());
  }

  function buildSingle(files) {
    const f = files[0];
    const note = files.length > 1 ? `<span class="muted small">Showing the first file; the selection applies to every file.</span>` : "";
    if (mode === "select") {
      const tb = `<button class="btn btn-sm" type="button" data-sel="all">All</button><button class="btn btn-sm" type="button" data-sel="none">None</button>
        <button class="btn btn-sm" type="button" data-sel="odd">Odd</button><button class="btn btn-sm" type="button" data-sel="even">Even</button>
        <button class="btn btn-sm" type="button" data-sel="invert">Invert</button><span class="muted small">Shift-click selects a range.</span>${note}`;
      mount(toolbar(tb) + `<div class="thumbs">${range(f.pages).map(p => thumbHtml({ fileIdx: 0, page: p, label: `Page ${p}`, cls: selected.has(p) ? "selected" : "" })).join("")}</div>`);
    } else {
      const tb = `<span class="muted small">Click between pages to cut after them.</span><button class="btn btn-sm" type="button" data-cuts="all">Cut after every page</button><button class="btn btn-sm" type="button" data-cuts="none">Clear cuts</button>${note}`;
      mount(toolbar(tb) + `<div class="thumbs">${range(f.pages).map(p => `<div class="cut">${thumbHtml({ fileIdx: 0, page: p, label: `Page ${p}` })}${p < f.pages ? `<div class="cut-mark ${cuts.has(p) ? "on" : ""}" data-cut="${p}" title="Split after page ${p}"><span class="scissors">${icon("scissors")}</span></div>` : ""}</div>`).join("")}</div>`);
    }
  }

  function syncItems(files) {
    // keep existing order/rotations for files that are still present, add new ones at the end
    const ids = files.map(f => f.id);
    items = items.filter(it => it.blank || ids.includes(it.fileId));
    items.forEach(it => { if (!it.blank) it.fileIdx = ids.indexOf(it.fileId); });
    files.forEach((f, idx) => {
      if (items.some(it => it.fileId === f.id)) return;
      range(pageCount(f)).forEach(p => items.push({ key: `${f.id}:${p}:${Math.random()}`, fileId: f.id, fileIdx: idx, page: p, rot: 0 }));
    });
  }

  function buildMulti(files) {
    syncItems(files);
    const multi = files.length > 1;
    const tb = mode === "rotate"
      ? `<button class="btn btn-sm" type="button" data-rot-all="-90">${icon("rotate-left")} Rotate all left</button><button class="btn btn-sm" type="button" data-rot-all="90">${icon("rotate")} Rotate all right</button><button class="btn btn-sm btn-ghost" type="button" data-reset>Reset</button>`
      : `<button class="btn btn-sm" type="button" data-blank-add>${icon("plus")} Blank page</button><button class="btn btn-sm" type="button" data-sort>Sort by file name</button><button class="btn btn-sm btn-ghost" type="button" data-reset>Reset</button><span class="muted small">Drag pages to reorder.</span>`;
    const tools = mode === "rotate"
      ? `<button type="button" data-rot="-90" title="Rotate left">${icon("rotate-left")}</button><button type="button" data-rot="90" title="Rotate right">${icon("rotate")}</button>`
      : `<button type="button" data-rot="90" title="Rotate">${icon("rotate")}</button><button type="button" data-dup title="Duplicate">${icon("copy")}</button><button type="button" data-del title="Delete">${icon("trash")}</button>`;
    mount(toolbar(tb) + `<div class="thumbs" data-sortable="${mode === "organize"}">${items.filter(it => !it.deleted).map(it => thumbHtml({
      fileIdx: it.blank ? -1 : it.fileIdx, page: it.page, key: it.key, rot: it.rot, blank: it.blank, cls: it.blank ? "blank" : "", tools,
      label: it.blank ? "Blank" : (multi ? `${String.fromCharCode(65 + it.fileIdx)}${it.page}` : `Page ${it.page}`) + (it.rot ? ` · ${it.rot}°` : ""),
    })).join("")}</div>`);
    root.querySelectorAll('[data-sortable="true"] .thumb').forEach(t => t.setAttribute("draggable", "true"));
  }

  let prefilledFor = null;
  async function prefillMetadata(f) {
    if (prefilledFor === f.id) return;
    prefilledFor = f.id;
    const r = await fetch(`/api/files/${f.id}/metadata`); if (!r.ok) return;
    const meta = await r.json();
    Object.entries(meta).forEach(([k, v]) => { const el = document.querySelector(`[name="metadata.${k}"]`); if (el) el.value = v; });
  }
  async function prefillBookmarks(f) {
    if (prefilledFor === f.id) return;
    prefilledFor = f.id;
    const r = await fetch(`/api/files/${f.id}/outline`); if (!r.ok) return;
    const j = await r.json(), ta = document.querySelector('[name="bookmarks"]');
    if (ta) { ta.value = j.text; ta.rows = Math.min(24, Math.max(6, j.text.split("\n").length + 2)); ta.placeholder = `Chapter 1 | 1\n  Section 1.1 | 2\nChapter 2 | ${Math.min(5, j.pages)}`; }
  }
  document.addEventListener("change", e => {
    if (mode !== "crop") return;
    if (e.target.name === "cropScope") { cropPage = 1; root.innerHTML = ""; build(); }
    if (e.target.name === "cropMode") build();
    if (e.target.matches("[data-area-page]")) { cropPage = +e.target.value; buildArea(pdfFiles()[0]); }
  });

  function buildArea(f, hint = "Draw a box around the text that identifies each document (page 1 shown).") {
    const scope = document.querySelector('input[name="cropScope"]:checked')?.value || "all";
    const key = scope === "individual" ? String(cropPage) : scope === "odd-even" ? (cropPage % 2 ? "odd" : "even") : "all";
    const crop = mode === "crop";
    if (crop) area = cropAreas[key] || null;
    const choices = crop && scope !== "all" ? (scope === "individual" ? range(f.pages) : range(Math.min(2, f.pages))) : [];
    const picker = choices.length ? `<label>Crop <select class="input" data-area-page aria-label="Page to crop">${choices.map(p => `<option value="${p}" ${p === cropPage ? "selected" : ""}>${scope === "odd-even" ? (p === 1 ? "Odd pages" : "Even pages") : `Page ${p}`}${cropAreas[scope === "individual" ? p : p === 1 ? "odd" : "even"] ? " ✓" : ""}</option>`).join("")}</select></label>` : "";
    if (crop) hint = scope === "all" ? "Draw one area for all pages." : "Draw an area for each page or group you want to crop. Other pages are kept.";
    root.innerHTML = `<div class="thumbs-toolbar"><span class="muted small">${esc(hint)}</span><span style="flex:1"></span>${picker}<button class="btn btn-sm btn-ghost" type="button" data-area-clear>Clear</button></div>
      <div style="padding:18px;text-align:center;background:var(--bg-sunken)"><div class="area-wrap"><canvas></canvas><div class="area-box" hidden></div></div></div>`;
    const wrap = root.querySelector(".area-wrap"), canvas = wrap.querySelector("canvas"), box = wrap.querySelector(".area-box");
    let pageSize = null;
    const pageNumber = crop ? cropPage : 1;
    loadDoc(f).then(doc => doc.getPage(pageNumber)).then(page => {
      if (!wrap.isConnected) return;
      const vp1 = page.getViewport({ scale: 1 });
      pageSize = { w: vp1.width, h: vp1.height };
      const cssW = Math.min(root.clientWidth - 40, 760), scale = cssW / vp1.width * (window.devicePixelRatio || 1);
      const vp = page.getViewport({ scale });
      canvas.width = vp.width; canvas.height = vp.height; canvas.style.width = cssW + "px";
      return page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
    }).then(() => paintArea()).catch(() => {});
    let start = null;
    const pt = e => { const r = canvas.getBoundingClientRect(); return { x: Math.max(0, Math.min(r.width, e.clientX - r.left)), y: Math.max(0, Math.min(r.height, e.clientY - r.top)), r }; };
    wrap.addEventListener("pointerdown", e => { start = pt(e); wrap.setPointerCapture(e.pointerId); });
    wrap.addEventListener("pointermove", e => {
      if (!start || !pageSize) return;
      const p = pt(e), k = pageSize.w / p.r.width;
      area = { x: Math.min(start.x, p.x) * k, y: Math.min(start.y, p.y) * k, width: Math.abs(p.x - start.x) * k, height: Math.abs(p.y - start.y) * k };
      if (crop) cropAreas[key] = area;
      paintArea();
    });
    wrap.addEventListener("pointerup", () => { start = null; if (area && (area.width < 3 || area.height < 3)) { area = null; if (crop) delete cropAreas[key]; paintArea(); } });
    root.querySelector("[data-area-clear]").onclick = () => { area = null; if (crop) delete cropAreas[key]; paintArea(); };
    function paintArea() {
      if (!area || !pageSize) { box.hidden = true; return; }
      const k = canvas.getBoundingClientRect().width / pageSize.w;
      Object.assign(box.style, { left: area.x * k + "px", top: area.y * k + "px", width: area.width * k + "px", height: area.height * k + "px" });
      box.hidden = false;
    }
  }

  // ---------------- interactions ----------------
  root.addEventListener("input", e => {
    if (e.target.matches("[data-zoom]")) { thumbW = +e.target.value; root.style.setProperty("--thumb", thumbW + "px"); }
  });

  root.addEventListener("click", e => {
    const t = e.target;
    const files = pdfFiles();
    if (mode === "select") {
      const sel = t.closest("[data-sel]");
      if (sel) {
        const n = files[0].pages, v = sel.dataset.sel;
        selected = new Set(v === "all" ? range(n) : v === "none" ? [] : v === "invert" ? range(n).filter(p => !selected.has(p))
          : range(n).filter(p => (p % 2 === 1) === (v === "odd")));
        lastClicked = null;
        return refreshSelect();
      }
      const th = t.closest(".thumb");
      if (th) {
        const p = +th.dataset.page;
        if (e.shiftKey && lastClicked) {  // range from the last clicked page, taking that page's state
          const on = selected.has(lastClicked);
          for (let q = Math.min(p, lastClicked); q <= Math.max(p, lastClicked); q++) on ? selected.add(q) : selected.delete(q);
        } else selected.has(p) ? selected.delete(p) : selected.add(p);
        lastClicked = p;
        return refreshSelect();
      }
    }
    if (mode === "split") {
      const c = t.closest("[data-cuts]");
      if (c) { cuts = new Set(c.dataset.cuts === "all" ? range(files[0].pages - 1) : []); build(); return syncSplit(); }
      const m = t.closest("[data-cut]");
      if (m) { const p = +m.dataset.cut; cuts.has(p) ? cuts.delete(p) : cuts.add(p); m.classList.toggle("on"); return syncSplit(); }
    }
    if (mode === "rotate" || mode === "organize") {
      if (t.closest("[data-reset]")) { items = []; return build(); }
      const all = t.closest("[data-rot-all]");
      if (all) { items.forEach(it => it.rot = norm(it.rot + +all.dataset.rotAll)); return build(); }
      if (t.closest("[data-blank-add]")) { items.push({ key: "blank" + Math.random(), blank: true, fileIdx: -1, page: -1, rot: 0 }); return build(); }
      if (t.closest("[data-sort]")) {
        const names = Tool.readyFiles().map(f => f.name);
        items.sort((a, b) => (a.blank - b.blank) || names[a.fileIdx].localeCompare(names[b.fileIdx], undefined, { numeric: true }) || a.page - b.page);
        return build();
      }
      const th = t.closest(".thumb"); if (!th) return;
      const it = items.find(x => x.key === th.dataset.key); if (!it) return;
      const rb = t.closest("[data-rot]");
      if (rb) { it.rot = norm(it.rot + +rb.dataset.rot); return build(); }
      if (t.closest("[data-del]")) { it.deleted = true; return build(); }
      if (t.closest("[data-dup]")) { items.splice(items.indexOf(it) + 1, 0, { ...it, key: it.key + "d" + Math.random() }); return build(); }
    }
  });

  // drag reorder (organize)
  let dragKey = null;
  root.addEventListener("dragstart", e => { const th = e.target.closest(".thumb"); if (th) { dragKey = th.dataset.key; e.dataTransfer.effectAllowed = "move"; } });
  root.addEventListener("dragover", e => {
    if (!dragKey) return; e.preventDefault();
    root.querySelectorAll(".drop-before").forEach(x => x.classList.remove("drop-before"));
    e.target.closest(".thumb")?.classList.add("drop-before");
  });
  root.addEventListener("drop", e => {
    if (!dragKey) return; e.preventDefault();
    const over = e.target.closest(".thumb");
    if (over && over.dataset.key === dragKey) { dragKey = null; return build(); }  // dropped on itself: no move
    const from = items.findIndex(x => x.key === dragKey);
    if (from < 0) { dragKey = null; return; }
    const [moved] = items.splice(from, 1);
    const to = over ? items.findIndex(x => x.key === over.dataset.key) : items.length;
    items.splice(to < 0 ? items.length : to, 0, moved);
    dragKey = null; build();
  });
  root.addEventListener("dragend", () => { dragKey = null; root.querySelectorAll(".drop-before").forEach(x => x.classList.remove("drop-before")); });

  // select <-> pages field
  const pagesInput = document.querySelector("[data-pages-input][name='pages']");
  function refreshSelect() {
    root.querySelectorAll(".thumb").forEach(th => th.classList.toggle("selected", selected.has(+th.dataset.page)));
    if (pagesInput) pagesInput.value = compressRanges([...selected]);
  }
  pagesInput?.addEventListener("input", () => {
    const n = pdfFiles()[0]?.pages || 0;
    if (mode === "split") {  // typed "3,7" -> cut marks after pages 3 and 7
      cuts = new Set(parseRanges(pagesInput.value, n).filter(p => p < n));
      root.querySelectorAll("[data-cut]").forEach(m => m.classList.toggle("on", cuts.has(+m.dataset.cut)));
      return;
    }
    if (mode !== "select") return;
    selected = new Set(parseRanges(pagesInput.value, n));
    root.querySelectorAll(".thumb").forEach(th => th.classList.toggle("selected", selected.has(+th.dataset.page)));
  });

  function syncSplit() {
    const radio = document.querySelector('input[name="splitMode"][value="after"]');
    if (cuts.size && radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
    if (pagesInput) pagesInput.value = [...cuts].sort((a, b) => a - b).join(",");
  }

  // params handed to tool.js on submit
  Tool.extraParams = body => {
    if (mode === "rotate") {
      const rots = items.filter(it => it.rot && !it.blank).map(it => `${it.fileIdx}:${it.page}:${it.rot}`);
      return rots.length ? { pageRotationsPerSource: rots } : {};
    }
    if (mode === "organize" && items.length) {
      return { filePages: items.filter(it => !it.deleted).map(it => it.blank ? `-1:-1:${it.rot}` : `${it.fileIdx}:${it.page}:${it.rot}`) };
    }
    if (mode === "crop") {
      const scope = document.querySelector('input[name="cropScope"]:checked')?.value || "all";
      return scope === "all" ? (cropAreas.all ? { area: roundObj(cropAreas.all) } : {}) : { cropAreas: Object.fromEntries(Object.entries(cropAreas).filter(([k]) => k !== "all").map(([k,v]) => [k, roundObj(v)])) };
    }
    if (mode === "area") return area ? { area: roundObj(area) } : {};
    return {};
  };
  Tool.validators.push(() => {
    if (mode === "organize" && items.length && !items.some(it => !it.deleted)) return "Keep at least one page";
    if (mode === "select" && ["extractPages", "deletePages"].includes(Tool.cfg.type) && pagesInput && !pagesInput.value.trim()) return "Select at least one page";
    if (mode === "crop" && document.querySelector('input[name="cropMode"]:checked')?.value === "area") {
      const scope = document.querySelector('input[name="cropScope"]:checked')?.value || "all";
      const found = scope === "all" ? !!cropAreas.all : Object.keys(cropAreas).some(k => scope === "individual" ? /^\d+$/.test(k) : ["odd", "even"].includes(k));
      if (!found) return "Draw the area to keep on the page";
    }
    return "";
  });

  document.addEventListener("files-changed", build);

  // helpers
  function range(n) { return Array.from({ length: n || 0 }, (_, i) => i + 1); }
  function norm(d) { return ((d % 360) + 360) % 360; }
  function roundObj(o) { return Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Math.round(v * 100) / 100])); }
  function parseRanges(s, n) {
    const out = [];
    String(s).split(",").forEach(part => {
      part = part.trim().toLowerCase(); if (!part) return;
      if (part === "odd" || part === "even") { range(n).forEach(p => { if ((p % 2 === 1) === (part === "odd")) out.push(p); }); return; }
      const m = part.match(/^(\d*)\s*-\s*(\d*)$/);
      if (m) { const a = +m[1] || 1, b = +m[2] || n; for (let p = Math.min(a, b); p <= Math.min(Math.max(a, b), n); p++) out.push(p); }
      else if (+part >= 1 && +part <= n) out.push(+part);
    });
    return out;
  }
})();
