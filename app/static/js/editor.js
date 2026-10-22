/* PDF editor (pages /pdf-editor, /sign-pdf, /pdf-forms).
 *
 * Model: every object lives on a page (by page key) with x, y, w, h in PDF points,
 * top-left origin, in the page's *displayed* orientation. On save these are converted
 * to bottom-left coordinates and sent as the operation arrays documented in
 * app/tools/editor.py. Page structure is sent as pageOrder ["orig:rot", "-1:0", …].
 */
(() => {
  const { $, icon, toast, dialog, esc } = window.UI;
  const Tool = window.Tool;
  const cfg = Tool.cfg;
  const ed = $("#editor"), pagesEl = $("#ed-pages"), props = $("#ed-props"), statusEl = $("#ed-status");
  // Desktop tools wrap; keep the properties strip below their actual height.
  const toolbar = ed.querySelector(".ed-bar");
  new ResizeObserver(() => {
    const top = parseFloat(getComputedStyle(toolbar).top) || 0;
    ed.style.setProperty("--editor-props-top", `${top + toolbar.getBoundingClientRect().height}px`);
  }).observe(toolbar);
  const DPR = Math.min(window.devicePixelRatio || 1, 2);
  const FONTS = [["Helvetica", "Sans"], ["Times", "Serif"], ["Courier", "Mono"]];
  const CSS_FONT = { Helvetica: "Helvetica, Arial, sans-serif", Times: "'Times New Roman', Times, serif", Courier: "'Courier New', monospace" };

  let file = null, doc = null, pages = [], objects = [], formValues = {}, zoom = 1, tool = "select", selected = null;
  let history = [], pendingImage = null, idSeq = 1, renderToken = 0, fieldDefs = new Map(), pdfFieldNames = new Set();
  const style = { font: "Helvetica", size: 14, color: "#111111", bold: false, italic: false, stroke: "#d6336c", fill: "", width: 2, mark: "#ffd43b" };

  // ------------------------------------------------------------------ open / close
  function tryOpen() {
    const f = Tool.readyFiles()[0];
    if (!f) return;
    if (file && file.id === f.id && doc) { show(); return; }
    open(f);
  }
  document.addEventListener("editor-open", tryOpen);
  document.addEventListener("files-changed", () => { if ($("#stage-result").hidden) tryOpen(); });
  document.addEventListener("editor-close", () => { ed.hidden = true; document.body.classList.remove("editing"); });

  function show() { ed.hidden = false; document.body.classList.add("editing"); window.scrollTo(0, 0); }

  async function open(f) {
    if (draftDirty && draftKey()) persistDraft();
    clearTimeout(draftTimer);
    draftIdentity = null;
    draftDirty = false;
    pruneDrafts();
    textCache.clear(); findMatches = []; findIndex = 0; findSequence++;
    $("#ed-find").hidden = true;
    file = f; show();
    pagesEl.innerHTML = `<div class="spinner"></div>`;
    try {
      await waitFor(() => window.pdfjsLib);
      pdfjsLib.GlobalWorkerOptions.workerSrc ||= "/static/vendor/pdfjs/pdf.worker.min.mjs";
      doc = await pdfjsLib.getDocument({ url: `/api/files/${f.id}/view`, password: f.password || undefined,
        isEvalSupported: false, cMapUrl: "/static/vendor/pdfjs/cmaps/", cMapPacked: true,
        standardFontDataUrl: "/static/vendor/pdfjs/standard_fonts/", wasmUrl: "/static/vendor/pdfjs/wasm/" }).promise;
      // Hash actual document bytes: PDFs can share a filename, size, or trailer ID.
      if (window.crypto?.subtle) {
        const hash = await crypto.subtle.digest("SHA-256", await doc.getData());
        draftIdentity = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
      } else draftIdentity = `${doc.fingerprints?.[0] || f.id}:${f.name}:${f.size}`;
    } catch (e) { pagesEl.innerHTML = `<div class="alert alert-err">Could not open this PDF.</div>`; return; }
    pages = []; objects = []; formValues = {}; history = []; fieldDefs = new Map();
    for (let i = 1; i <= doc.numPages; i++) {
      const p = await doc.getPage(i);
      pages.push({ key: "p" + i, orig: i, rot: 0, base: p.rotate, view: p.view });
    }
    try { pdfFieldNames = new Set(Object.keys((await doc.getFieldObjects()) || {})); } catch { pdfFieldNames = new Set(); }
    const maxW = Math.max(...pages.map(p => size(p).w));
    zoom = clamp((pagesEl.clientWidth || 900) / (maxW + 60), 0.5, 1.25);
    setTool(cfg.type === "fillSign" ? "select" : cfg.type === "editForms" ? "field-text" : "text");
    $("#flatten-wrap").hidden = cfg.type === "edit";
    await offerRecovery();
    renderAll();
  }

  function waitFor(fn) { return new Promise(r => { const t = () => fn() ? r() : setTimeout(t, 60); t(); }); }
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /** displayed size in points of a page entry */
  function size(p) {
    if (p.orig === -1) return p.rot % 180 ? { w: p.h, h: p.w } : { w: p.w, h: p.h };
    const [x0, y0, x1, y1] = p.view, r = (p.base + p.rot) % 180;
    return r ? { w: y1 - y0, h: x1 - x0 } : { w: x1 - x0, h: y1 - y0 };
  }

  // ------------------------------------------------------------------ rendering
  function renderAll() {
    const token = ++renderToken;
    lazy.disconnect();
    pagesEl.innerHTML = "";
    $("#ed-zoom").textContent = Math.round(zoom * 100) + "%";
    pages.forEach((p, idx) => {
      const { w, h } = size(p);
      const wrap = document.createElement("div");
      wrap.className = "ed-pagewrap"; wrap.dataset.key = p.key;
      wrap.innerHTML = `
        <div class="ed-pagebar">Page ${idx + 1}
          <button type="button" data-pa="rotl" title="Rotate left">${icon("rotate-left")}</button>
          <button type="button" data-pa="rotr" title="Rotate right">${icon("rotate")}</button>
          <button type="button" data-pa="del" title="Delete page">${icon("trash")}</button>
          <button type="button" data-pa="ins" title="Insert a blank page after this one">${icon("plus")} Blank page</button>
        </div>
        <div class="ed-page" style="width:${w * zoom}px;height:${h * zoom}px"><canvas class="pdf"></canvas><div class="layer fields"></div><div class="layer texts"></div><div class="layer objs"></div></div>`;
      pagesEl.appendChild(wrap);
      lazy.observe(wrap);
      wrap._token = token;
      renderObjects(p.key);
    });
    showFindMatch(false);
  }

  const lazy = new IntersectionObserver(entries => entries.forEach(en => {
    if (!en.isIntersecting) return;
    lazy.unobserve(en.target);
    drawPage(en.target);
  }), { rootMargin: "600px" });

  async function drawPage(wrap) {
    const p = pages.find(x => x.key === wrap.dataset.key); if (!p) return;
    const canvas = wrap.querySelector("canvas.pdf"), { w, h } = size(p);
    canvas.width = Math.round(w * zoom * DPR); canvas.height = Math.round(h * zoom * DPR);
    const ctx = canvas.getContext("2d");
    if (p.orig === -1) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height); return; }
    const page = await doc.getPage(p.orig);
    const vp = page.getViewport({ scale: zoom * DPR, rotation: (p.base + p.rot) % 360 });
    // form widgets are drawn as HTML inputs on top, so leave them out of the canvas (no doubled values)
    await page.render({ canvasContext: ctx, viewport: vp, annotationMode: pdfjsLib.AnnotationMode.ENABLE_FORMS }).promise;
    if (wrap._token !== renderToken) return;
    const vp1 = page.getViewport({ scale: 1, rotation: (p.base + p.rot) % 360 });
    renderFields(wrap, p, page, vp1);
    if (tool === "edittext") renderTextSpans(wrap, p, page, vp1);
  }

  async function renderFields(wrap, p, page, vp1) {
    const layer = wrap.querySelector(".fields");
    const annots = await page.getAnnotations({ intent: "display" });
    layer.innerHTML = "";
    for (const a of annots) {
      if (a.subtype !== "Widget" || !a.fieldName) continue;
      const [x0, y0] = vp1.convertToViewportPoint(a.rect[0], a.rect[1]);
      const [x1, y1] = vp1.convertToViewportPoint(a.rect[2], a.rect[3]);
      const L = Math.min(x0, x1), T = Math.min(y0, y1), W = Math.abs(x1 - x0), H = Math.abs(y1 - y0);
      let el;
      const name = a.fieldName;
      const cur = formValues[name];
      if (a.fieldType === "Tx") {
        el = document.createElement(a.multiLine ? "textarea" : "input");
        el.value = cur ?? (a.fieldValue || "");
        if (a.maxLen) el.maxLength = a.maxLen;
      } else if (a.fieldType === "Btn" && a.checkBox) {
        el = document.createElement("input"); el.type = "checkbox";
        el.checked = cur !== undefined ? !!cur : (a.fieldValue && a.fieldValue !== "Off");
      } else if (a.fieldType === "Btn" && a.radioButton) {
        el = document.createElement("input"); el.type = "radio"; el.name = "rf-" + name; el.value = a.buttonValue;
        el.checked = cur !== undefined ? cur === a.buttonValue : a.fieldValue === a.buttonValue;
      } else if (a.fieldType === "Ch") {
        el = document.createElement("select");
        el.innerHTML = (a.options || []).map(o => `<option value="${esc(o.exportValue)}">${esc(o.displayValue)}</option>`).join("");
        el.multiple = !!a.multiSelect;
        if (!a.combo) el.size = Math.max(2, Math.min(8, (a.options || []).length));
        const values = cur ?? a.fieldValue ?? [];
        if (el.multiple) [...el.options].forEach(opt => { opt.selected = (Array.isArray(values) ? values : [values]).includes(opt.value); });
        else el.value = (Array.isArray(values) ? values[0] : values) ?? "";
      } else continue;
      el.className = "formfield"; el.dataset.field = name;
      if (a.readOnly) el.disabled = true;
      Object.assign(el.style, { left: L * zoom + "px", top: T * zoom + "px", width: W * zoom + "px", height: H * zoom + "px", fontSize: Math.max(8, Math.min(H * 0.7, 14)) * zoom + "px" });
      el.addEventListener("pointerdown", e => e.stopPropagation());
      el.addEventListener("change", () => {
        formValues[name] = el.type === "checkbox" ? el.checked : el.tagName === "SELECT" && el.multiple ? [...el.selectedOptions].map(opt => opt.value) : el.value;
        saveDraft();
      });
      el.addEventListener("input", () => { if (el.tagName !== "SELECT" && el.type !== "checkbox" && el.type !== "radio") { formValues[name] = el.value; saveDraft(); } });
      layer.appendChild(el);
    }
  }

  async function renderTextSpans(wrap, p, page, vp1) {
    const layer = wrap.querySelector(".texts");
    layer.innerHTML = "";
    const tc = await page.getTextContent();
    const used = new Set(objects.filter(o => o.type === "edittext" && o.page === p.key).flatMap(o => o.srcIndices || [o.srcIdx]));
    tc.items.forEach((it, i) => {
      if (!it.str.trim() || used.has(i)) return;
      const tx = pdfjsLib.Util.transform(vp1.transform, it.transform);
      const angle = Math.atan2(tx[1], tx[0]);
      if (Math.abs(angle) > 0.01) return;
      const fh = Math.hypot(tx[2], tx[3]);
      const left = tx[4], top = tx[5] - fh, width = it.width * (vp1.scale || 1);
      const st = tc.styles[it.fontName] || {};
      const span = document.createElement("span");
      span.className = "edit-span"; span.textContent = it.str;
      Object.assign(span.style, { left: left * zoom + "px", top: top * zoom + "px", width: width * zoom + "px", height: fh * 1.2 * zoom + "px", fontSize: fh * zoom + "px" });
      span.addEventListener("pointerdown", e => {
        e.stopPropagation();
        const fam = /mono|courier/i.test(st.fontFamily || it.fontName) ? "Courier" : /serif/i.test(st.fontFamily || "") && !/sans/i.test(st.fontFamily || "") ? "Times" : "Helvetica";
        push();
        const props0 = { font: fam, size: round2(fh), bold: /bold/i.test(it.fontName + (st.fontFamily || "")), italic: /italic|oblique/i.test(it.fontName) };
        // o.y is the top of the line box; place it so the new baseline sits on the old one (tx[5])
        const o = add({ type: "edittext", page: p.key, x: left, y: tx[5] - baseK(props0) * fh, w: width, h: fh * 1.2, text: it.str, srcIdx: i,
          area: { x: left - 1, y: top - 1, w: width + 2, h: fh * 1.25 + 2 }, color: "#000000", ...props0 });
        span.remove(); select(o, true);
      });
      layer.appendChild(span);
    });
  }

  // ------------------------------------------------------------------ find / visual replacement
  const textCache = new Map();
  let findMatches = [], findIndex = 0, findSequence = 0, findTimer = null;
  const findPanel = $("#ed-find");
  const foundOccurrences = text => {
    const needle = $("#ed-find-text").value;
    if (!needle) return [];
    const sensitive = $("#ed-find-case").checked;
    const haystack = sensitive ? text : text.toLowerCase(), query = sensitive ? needle : needle.toLowerCase();
    const positions = [];
    for (let at = haystack.indexOf(query); at !== -1; at = haystack.indexOf(query, at + query.length)) positions.push(at);
    return positions;
  };
  async function findRows() {
    const rows = [], sourceDoc = doc;
    for (const entry of [...pages]) {
      if (sourceDoc !== doc) return [];
      if (entry.orig === -1) continue;
      let data = textCache.get(entry.orig);
      if (!data) {
        const page = await sourceDoc.getPage(entry.orig);
        data = { page, content: await page.getTextContent() };
        if (sourceDoc !== doc) return [];
        textCache.set(entry.orig, data);
      }
      const viewport = data.page.getViewport({ scale: 1, rotation: (entry.base + entry.rot) % 360 });
      const used = new Set(objects.filter(o => o.type === "edittext" && o.page === entry.key).flatMap(o => o.srcIndices || [o.srcIdx]));
      let line = null;
      data.content.items.forEach((item, idx) => {
        if (!item.str || used.has(idx)) { line = null; return; }
        const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
        if (Math.abs(Math.atan2(tx[1], tx[0])) > 0.01) { line = null; return; }
        const height = Math.hypot(tx[2], tx[3]), left = tx[4], width = item.width;
        const gap = line ? left - line.right : 0;
        if (line && line.fontName === item.fontName && Math.abs(line.baseline - tx[5]) < 1 && gap >= -1 && gap < height * 1.5) {
          const space = gap > height * 0.15 && !/\s$/.test(line.text) && !/^\s/.test(item.str) ? " " : "";
          line.text += space + item.str; line.right = Math.max(line.right, left + width);
          line.w = line.right - line.x; line.area.w = line.w + 2; line.srcIndices.push(idx);
        } else {
          const font = data.content.styles[item.fontName] || {};
          const family = /mono|courier/i.test(font.fontFamily || item.fontName) ? "Courier" : /serif/i.test(font.fontFamily || "") && !/sans/i.test(font.fontFamily || "") ? "Times" : "Helvetica";
          const properties = { font: family, size: round2(height), bold: /bold/i.test(item.fontName + (font.fontFamily || "")), italic: /italic|oblique/i.test(item.fontName) };
          line = { page: entry.key, text: item.str, x: left, y: tx[5] - baseK(properties) * height, w: width, h: height * 1.2,
            area: { x: left - 1, y: tx[5] - height - 1, w: width + 2, h: height * 1.25 + 2 }, color: "#000000", ...properties,
            srcIdx: idx, srcIndices: [idx], baseline: tx[5], right: left + width, fontName: item.fontName };
          rows.push(line);
        }
        if (item.hasEOL) line = null;
      });
      objects.filter(o => o.type === "edittext" && o.page === entry.key).forEach(o => rows.push({ ...o, existingId: o.id }));
    }
    return rows;
  }
  async function searchText() {
    const sequence = ++findSequence;
    $("#ed-find-count").textContent = "Searching…";
    $("#ed-find-replace").disabled = $("#ed-find-all").disabled = true;
    try {
      const rows = await findRows();
      if (sequence !== findSequence) return;
      const length = $("#ed-find-text").value.length;
      findMatches = rows.flatMap(row => foundOccurrences(row.text).map(start => ({ row, start, end: start + length })));
      findIndex = Math.min(findIndex, Math.max(0, findMatches.length - 1));
      const count = findMatches.length;
      $("#ed-find-count").textContent = count ? `${count} match${count === 1 ? "" : "es"}` : $("#ed-find-text").value ? "No matches in horizontal text." : "Enter text to find.";
      $("#ed-find-results").innerHTML = findMatches.map((match, idx) => `<option value="${idx}">Page ${pages.findIndex(p => p.key === match.row.page) + 1}: ${esc(match.row.text.slice(Math.max(0, match.start - 25), match.end + 50))}</option>`).join("");
      $("#ed-find-results").disabled = $("#ed-find-replace").disabled = $("#ed-find-all").disabled = !count;
      showFindMatch();
    } catch { $("#ed-find-count").textContent = "Could not search this document. Try again."; }
  }
  function showFindMatch(scroll = true) {
    pagesEl.querySelectorAll(".ed-find-mark").forEach(el => el.remove());
    if (findPanel.hidden) return;
    const match = findMatches[findIndex];
    if (!match) return;
    $("#ed-find-results").value = String(findIndex);
    const page = pagesEl.querySelector(`.ed-pagewrap[data-key="${match.row.page}"] .ed-page`);
    if (!page) return;
    const mark = document.createElement("div"), area = match.row.area;
    mark.className = "ed-find-mark";
    Object.assign(mark.style, { position: "absolute", pointerEvents: "none", outline: "2px solid #f59f00", background: "rgba(255,212,59,.18)", zIndex: 5,
      left: area.x * zoom + "px", top: area.y * zoom + "px", width: area.w * zoom + "px", height: area.h * zoom + "px" });
    page.appendChild(mark);
    if (scroll) mark.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  async function replaceFound(all) {
    clearTimeout(findTimer);
    await searchText();
    const matches = all ? findMatches : findMatches.slice(findIndex, findIndex + 1);
    if (!matches.length) return;
    const replacement = $("#ed-replace-text").value;
    const grouped = new Map();
    matches.forEach(match => { if (!grouped.has(match.row)) grouped.set(match.row, []); grouped.get(match.row).push(match); });
    push();
    for (const [row, hits] of grouped) {
      let text = row.text;
      hits.sort((a, b) => b.start - a.start).forEach(hit => { text = text.slice(0, hit.start) + replacement + text.slice(hit.end); });
      const existing = row.existingId ? byId(row.existingId) : null;
      if (existing) existing.text = text;
      else {
        const { baseline, right, fontName, existingId, ...properties } = row;
        add({ ...properties, type: "edittext", text });
      }
      renderObjects(row.page);
    }
    saveDraft();
    toast(`Replaced ${matches.length} match${matches.length === 1 ? "" : "es"}`);
    await searchText();
  }
  $("#ed-find-search").addEventListener("click", searchText);
  $("#ed-find-text").addEventListener("input", () => { clearTimeout(findTimer); findIndex = 0; findTimer = setTimeout(searchText, 200); });
  $("#ed-find-case").addEventListener("change", searchText);
  $("#ed-find-results").addEventListener("change", e => { findIndex = Number(e.target.value); showFindMatch(); });
  $("#ed-find-replace").addEventListener("click", () => replaceFound(false));
  $("#ed-find-all").addEventListener("click", () => replaceFound(true));
  $("#ed-find-close").addEventListener("click", () => { findPanel.hidden = true; showFindMatch(false); });
  [$("#ed-find-text"), $("#ed-replace-text")].forEach(input => input.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); searchText(); }
  }));

  function renderObjects(key) {
    const wrap = pagesEl.querySelector(`.ed-pagewrap[data-key="${key}"]`); if (!wrap) return;
    const layer = wrap.querySelector(".objs");
    layer.innerHTML = "";
    objects.filter(o => o.page === key).forEach(o => layer.appendChild(objEl(o)));
  }

  function objEl(o) {
    const el = document.createElement("div");
    el.className = "obj " + o.type + (selected === o ? " sel" : "");
    el.dataset.id = o.id;
    const z = zoom;
    Object.assign(el.style, { left: o.x * z + "px", top: o.y * z + "px" });
    if (o.type === "text" || o.type === "edittext") {
      el.classList.add("text");
      if (o.type === "edittext") {
        // the white box covers exactly the area that is whited out on save; longer text overflows it, as in the PDF
        Object.assign(el.style, { left: o.area.x * z + "px", top: o.area.y * z + "px", width: o.area.w * z + "px", height: o.area.h * z + "px", background: "#fff" });
      }
      const span = document.createElement("span");
      span.contentEditable = "true"; span.spellcheck = false; span.textContent = o.text;
      Object.assign(span.style, { fontFamily: CSS_FONT[o.font] || CSS_FONT.Helvetica, fontSize: o.size * z + "px", color: o.color,
        fontWeight: o.bold ? "700" : "400", fontStyle: o.italic ? "italic" : "normal", lineHeight: "1.2" });
      if (o.type === "edittext") Object.assign(span.style, { position: "absolute", left: (o.x - o.area.x) * z + "px", top: (o.y - o.area.y) * z + "px" });
      span.addEventListener("input", () => { o.text = span.innerText.replace(/\n$/, ""); saveDraft(); });
      span.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== span) dropIfEmpty(o); }, 0));
      span.addEventListener("focus", () => { if (o._snap !== o.text) { push(); o._snap = o.text; } if (selected !== o) select(o, false); });
      span.addEventListener("keydown", e => { if (e.key === "Escape") span.blur(); e.stopPropagation(); });
      span.addEventListener("paste", e => { e.preventDefault(); document.execCommand("insertText", false, e.clipboardData.getData("text/plain")); });
      el.appendChild(span);
      if (o.type === "text") el.insertAdjacentHTML("beforeend", `<span class="h" data-handle title="Drag to resize the text"></span>`);
    } else {
      Object.assign(el.style, { width: o.w * z + "px", height: o.h * z + "px" });
      if (o.type === "image") {
        el.innerHTML = `<img alt="${o.signature ? "Signature" : ""}" src="${o.src}">`;
        if (o.signature) {
          el.classList.add("signature-object");
          el.insertAdjacentHTML("beforeend", `<div class="signature-object-actions"><button type="button" data-object-action="rotate" aria-label="Rotate signature">${icon("rotate")}</button><button type="button" data-object-action="duplicate" aria-label="Duplicate signature">${icon("copy")}</button><button type="button" data-object-action="delete" aria-label="Delete signature">${icon("trash")}</button></div>`);
        }
      }
      if (o.type === "shape") Object.assign(el.style, {
        background: o.fill || "transparent", border: o.strokeWidth ? `${o.strokeWidth * z}px solid ${o.stroke}` : "none",
        borderRadius: o.shape === "ellipse" ? "50%" : "0" });
      if (o.type === "mark") {
        if (o.kind === "highlight") Object.assign(el.style, { background: o.color, opacity: 0.4, mixBlendMode: "multiply" });
        else el.innerHTML = `<svg><line x1="0" x2="100%" y1="${o.kind === "strikethrough" ? "50%" : "92%"}" y2="${o.kind === "strikethrough" ? "50%" : "92%"}" stroke="${o.color}" stroke-width="${Math.max(1, o.h * 0.08 * z)}"/></svg>`;
      }
      // lines and drawings get a padded box so thin/horizontal ones can still be clicked
      const pad = ["line", "draw"].includes(o.type) ? Math.max(6, o.width) : 0;
      if (pad) Object.assign(el.style, { left: (o.x - pad) * z + "px", top: (o.y - pad) * z + "px", width: (o.w + 2 * pad) * z + "px", height: (o.h + 2 * pad) * z + "px" });
      const X = v => (v - o.x + pad) * z, Y = v => (v - o.y + pad) * z;
      if (o.type === "line") {
        el.classList.add("svgobj");
        let { x1, y1, x2, y2 } = o, head = "";
        if (o.kind === "arrow") { // same geometry as the server (editor.py _arrow_head)
          const hs = Math.max(6, o.width * 4), ang = Math.atan2(y2 - y1, x2 - x1);
          const pt = d => `${X(x2 - hs * Math.cos(ang + d))},${Y(y2 - hs * Math.sin(ang + d))}`;
          head = `<polygon fill="${o.color}" points="${X(x2)},${Y(y2)} ${pt(-0.45)} ${pt(0.45)}"/>`;
          x2 -= hs * 0.7 * Math.cos(ang); y2 -= hs * 0.7 * Math.sin(ang);
        }
        el.innerHTML = `<svg><line x1="${X(x1)}" y1="${Y(y1)}" x2="${X(x2)}" y2="${Y(y2)}" stroke="${o.color}" stroke-width="${o.width * z}" stroke-linecap="round"/>${head}</svg>`;
      }
      if (o.type === "draw") {
        el.classList.add("svgobj");
        el.innerHTML = `<svg>${o.strokes.map(s => `<polyline fill="none" stroke="${o.color}" stroke-width="${o.width * z}" stroke-linecap="round" stroke-linejoin="round" points="${chunk(s).map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")}"/>`).join("")}</svg>`;
      }
      if (o.type === "link") el.innerHTML = `<span class="tag">${icon("link")} ${esc(o.href)}</span>`;
      if (o.type === "field") {
        el.title = o.name;
        if (["checkbox", "radio"].includes(o.kind)) {
          Object.assign(el.style, { padding: "0", borderWidth: Math.max(0.75, z) + "px", borderRadius: o.kind === "radio" ? "50%" : "0" });
          if (o.value) el.innerHTML = o.kind === "radio" ? `<svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="3.5" fill="#5b47d6"/></svg>`
            : `<svg viewBox="0 0 14 14"><path d="M2 7 L5.5 10.5 L12 3" fill="none" stroke="#5b47d6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        } else el.textContent = o.value ? String(o.value) : o.name;
      }
      if (!["line", "draw"].includes(o.type)) el.insertAdjacentHTML("beforeend", `<span class="h" data-handle></span>`);
    }
    el.insertAdjacentHTML("beforeend", `<button type="button" class="x" data-del title="Delete">×</button>`);
    return el;
  }

  // Where the browser puts the first baseline inside a line box (line-height 1.2), as a fraction of the font size.
  // Measured once per font so the saved text lands exactly where it is shown.
  const blCache = {};
  function baseK(o) {
    const key = `${o.font}|${o.bold ? 1 : 0}|${o.italic ? 1 : 0}`;
    if (blCache[key]) return blCache[key];
    const d = document.createElement("div");
    d.style.cssText = `position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;font-family:${CSS_FONT[o.font] || CSS_FONT.Helvetica};font-size:100px;line-height:1.2;font-weight:${o.bold ? 700 : 400};font-style:${o.italic ? "italic" : "normal"}`;
    d.innerHTML = `<span>Hg</span><span style="display:inline-block;width:1px;height:0"></span>`;
    document.body.appendChild(d);
    const k = (d.lastChild.getBoundingClientRect().bottom - d.getBoundingClientRect().top) / 100;
    d.remove();
    return (blCache[key] = k > 0.5 && k < 1.5 ? k : 0.93);
  }
  /** an added text box that was left empty is removed when it loses focus */
  function dropIfEmpty(o) {
    if (!o || o.type !== "text" || o.text.trim() || !objects.includes(o) || selected === o) return;
    objects = objects.filter(x => x !== o);
    renderObjects(o.page); saveDraft();
  }
  const meaningful = () => objects.filter(o => o.type !== "text" || o.text.trim());

  const chunk = a => a.reduce((acc, v, i) => (i % 2 ? acc[acc.length - 1].push(v) : acc.push([v]), acc), []);
  const round2 = v => Math.round(v * 100) / 100;

  // ------------------------------------------------------------------ state helpers
  function add(o) { o.id = idSeq++; objects.push(o); renderObjects(o.page); saveDraft(); return o; }
  function remove(o) { push(); objects = objects.filter(x => x !== o); if (selected === o) selected = null; renderObjects(o.page); paintProps(); saveDraft();
    if (o.type === "edittext" && tool === "edittext") refreshPage(o.page); }
  function push() { history.push(JSON.stringify({ pages, objects, formValues })); if (history.length > 80) history.shift(); }
  function undo() {
    const s = history.pop(); if (!s) return toast("Nothing to undo");
    const st = JSON.parse(s); pages = st.pages; objects = st.objects; formValues = st.formValues; selected = null;
    renderAll(); paintProps(); saveDraft();
    if (!findPanel.hidden) searchText();
  }
  function select(o, focus) {
    const prev = selected;
    selected = o;
    if (prev && prev !== o) dropIfEmpty(prev);
    pagesEl.querySelectorAll(".obj.sel").forEach(el => el.classList.remove("sel"));
    if (o) {
      let el = pagesEl.querySelector(`.obj[data-id="${o.id}"]`);
      if (!el) { renderObjects(o.page); el = pagesEl.querySelector(`.obj[data-id="${o.id}"]`); }
      el?.classList.add("sel");
      if (focus) setTimeout(() => { const s = el?.querySelector("[contenteditable]"); if (s) { s.focus(); placeCaretEnd(s); } }, 0);
    }
    paintProps();
  }
  /** picking a tool ends the current selection, so the style bar edits the next object, not the last one */
  function deselect() {
    if (!selected) return;
    const prev = selected; selected = null;
    document.activeElement?.blur?.();
    renderObjects(prev.page); paintProps(); dropIfEmpty(prev);
  }
  function placeCaretEnd(el) { if (!el) return; const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
  function refreshPage(key) { const w = pagesEl.querySelector(`.ed-pagewrap[data-key="${key}"]`); if (w) drawPage(w); }

  // ------------------------------------------------------------------ toolbar & props
  function setTool(t) {
    tool = t;
    ed.querySelectorAll("[data-tool]").forEach(b => b.setAttribute("aria-pressed", b.dataset.tool === t));
    const hints = { select: "Click an item to select it. Drag to move, drag the corner to resize.", text: "Click on the page to add text.",
      edittext: "Click any text in the document to change it.", whiteout: "Drag over content to hide it with white.",
      rect: "Drag to draw a box.", ellipse: "Drag to draw a circle.", line: "Drag to draw a line.", arrow: "Drag to draw an arrow.",
      draw: "Draw freehand on the page.", highlight: "Drag over text to highlight it.", strike: "Drag over text to strike it through.",
      underline: "Drag under text to underline it.", link: "Drag over an area to make it a link.", "field-text": "Drag to add a fillable text box.",
      "field-check": "Click to add a checkbox.", "field-radio": "Click to add a radio button. Give buttons the same field name to group them.",
      "field-dropdown": "Drag to add a dropdown, then set its options.", "field-listbox": "Drag to add a list box, then set its options.",
      sign: "Click on the page to place your signature.", image: "Click on the page to place the image." };
    statusEl.textContent = hints[t] || "";
    pagesEl.style.cursor = t === "select" ? "default" : "crosshair";
    pagesEl.classList.toggle("drag-tool", !["select", "edittext", "text", "sign", "image", "field-check", "field-radio"].includes(t));
    objects.forEach(o => delete o._live);
    pagesEl.querySelectorAll(".texts").forEach(l => l.innerHTML = "");
    if (t === "edittext") pagesEl.querySelectorAll(".ed-pagewrap").forEach(w => { if (w.querySelector("canvas").width) drawPage(w); });
    paintProps();
  }

  ed.querySelector(".ed-bar").addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.tool === "sign" || b.dataset.tool === "image") deselect();
    if (b.dataset.tool === "sign") { const src = await window.PDFNovaSignatures.choose(b); if (!src) return; pendingImage = { src: src.dataUrl, ratio: src.ratio, sig: true }; setTool("sign"); return; }
    if (b.dataset.tool === "image") { $("#ed-image-input").click(); return; }
    if (b.dataset.tool) { deselect(); return setTool(b.dataset.tool); }
    const a = b.dataset.action;
    if (a === "find") { deselect(); setTool("select"); findPanel.hidden = !findPanel.hidden; if (!findPanel.hidden) { $("#ed-find-text").focus(); searchText(); } else showFindMatch(false); }
    if (a === "undo") undo();
    if (a === "zoom-in" || a === "zoom-out") { zoom = clamp(zoom * (a === "zoom-in" ? 1.2 : 1 / 1.2), 0.4, 3); renderAll(); }
    if (a === "date") { deselect(); pendingImage = null; setTool("text"); style._dateNext = true; statusEl.textContent = "Click on the page to insert today's date."; }
  });

  $("#ed-image-input").addEventListener("change", async e => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    const { dataUrl, ratio } = await fileToDataUrl(f, 1800);
    pendingImage = { src: dataUrl, ratio }; setTool("image");
  });

  function paintProps() {
    const o = selected;
    const kind = o ? o.type : { text: "text", edittext: "text", rect: "shape", ellipse: "shape", line: "line", arrow: "line", draw: "line",
      highlight: "mark", strike: "mark", underline: "mark" }[tool];
    const src = o || style;
    let html = "";
    if (kind === "text" || kind === "edittext") {
      html = `<label>Font <select data-p="font">${FONTS.map(([v, l]) => `<option value="${v}" ${src.font === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>Size <input type="number" min="4" max="200" step="1" data-p="size" value="${Math.round(src.size)}"></label>
        <label>Color <input type="color" data-p="color" value="${src.color}"></label>
        <button type="button" class="tog" data-t="bold" aria-pressed="${!!src.bold}"><b>B</b></button>
        <button type="button" class="tog" data-t="italic" aria-pressed="${!!src.italic}"><i>I</i></button>`;
    } else if (kind === "shape") {
      html = `<label>Border <input type="color" data-p="stroke" value="${src.stroke || "#000000"}"></label>
        <label>Width <input type="number" min="0" max="20" data-p="strokeWidth" value="${o ? o.strokeWidth : style.width}"></label>
        <label>Fill <input type="color" data-p="fill" value="${src.fill || "#ffffff"}"></label>
        <button type="button" class="tog" data-t="nofill" aria-pressed="${!src.fill}">No fill</button>`;
    } else if (kind === "line" || kind === "draw") {
      html = `<label>Color <input type="color" data-p="${o ? "color" : "stroke"}" value="${o ? o.color : style.stroke}"></label>
        <label>Width <input type="number" min="1" max="20" data-p="width" value="${o ? o.width : style.width}"></label>`;
    } else if (kind === "mark") {
      html = `<label>Color <input type="color" data-p="${o ? "color" : "mark"}" value="${o ? o.color : style.mark}"></label>`;
    } else if (kind === "link" && o) {
      html = `<label>Link to <input type="text" data-p="href" value="${esc(o.href)}" style="width:260px;padding:5px 8px;border:1px solid var(--line-strong);border-radius:8px"></label>`;
    } else if (kind === "field" && o) {
      html = `<label>Field name <input type="text" data-p="name" value="${esc(o.name)}" style="width:180px;padding:5px 8px;border:1px solid var(--line-strong);border-radius:8px"></label>
        ${o.kind === "text" ? `<label>Default value <input type="text" data-p="value" value="${esc(o.value || "")}"></label>
          <label>Max characters <input type="number" min="0" max="100000" data-p="maxLength" value="${o.maxLength || 0}" title="0 means unlimited"></label>
          <label class="check"><input type="checkbox" data-c="multiline" ${o.multiline ? "checked" : ""}> Multi-line</label>
          <label class="check"><input type="checkbox" data-c="comb" ${o.comb ? "checked" : ""}> One character per box</label>` : ""}
        ${["dropdown", "listbox"].includes(o.kind) ? `<label>Options (one per line)<textarea data-p="options" rows="2">${esc((o.options || []).map(v => typeof v === "object" ? v.value : v).join("\n"))}</textarea></label>
          <label>Default value${o.multiSelect ? "s (one per line)" : ""}<textarea data-p="value" rows="2">${esc(Array.isArray(o.value) ? o.value.join("\n") : o.value || "")}</textarea></label>
          ${o.kind === "listbox" ? `<label class="check"><input type="checkbox" data-c="multiSelect" ${o.multiSelect ? "checked" : ""}> Multiple selection</label>` : ""}` : ""}
        ${["checkbox", "radio"].includes(o.kind) ? `<label class="check"><input type="checkbox" data-c="value" ${o.value ? "checked" : ""}> Selected by default</label>` : ""}
        ${o.kind === "radio" ? `<label>Option value <input type="text" data-p="exportValue" value="${esc(o.exportValue || "Yes")}" title="Use a unique value for each button in the same group"></label>` : ""}
        <label class="check"><input type="checkbox" data-c="required" ${o.required ? "checked" : ""}> Required</label>`;
    } else if (kind === "image" && o) {
      html = `<label>Opacity <input type="range" min="10" max="100" data-p="opacity" value="${Math.round((o.opacity ?? 1) * 100)}"></label>`;
    }
    props.innerHTML = html; props.hidden = !html;
  }

  props.addEventListener("input", e => {
    const k = e.target.dataset.p, c = e.target.dataset.c; if (!k && !c) return;
    const o = selected;
    let v = e.target.type === "number" || e.target.type === "range" ? Number(e.target.value) : e.target.value;
    if (k === "opacity") v = v / 100;
    if (o) {
      if (!props._pushed) { push(); props._pushed = true; setTimeout(() => props._pushed = false, 800); }
      if (k === "options") v = v.split("\n").map(x => x.trim()).filter(Boolean);
      if (k === "value" && o.multiSelect) v = v.split("\n").map(x => x.trim()).filter(Boolean);
      if (c) o[c] = e.target.checked; else o[k] = v;
      if (c === "comb" && o.comb) { o.multiline = false; o.maxLength ||= 10; }
      if (c === "multiline" && o.multiline) o.comb = false;
      if (c === "multiSelect") o.value = o.multiSelect ? (Array.isArray(o.value) ? o.value : o.value ? [o.value] : []) : (Array.isArray(o.value) ? o.value[0] || "" : o.value || "");
      if (c === "value" && o.kind === "radio" && o.value) objects.filter(other => other !== o && other.kind === "radio" && other.name === o.name).forEach(other => { other.value = false; renderObjects(other.page); });
      if (k === "width" && o.type === "shape") o.strokeWidth = v;
      renderObjects(o.page); saveDraft();
      if (["comb", "multiline", "multiSelect"].includes(c)) paintProps();
    } else if (k) {
      if (k === "strokeWidth") style.width = v; else style[k] = v;
    }
  });
  props.addEventListener("click", e => {
    const t = e.target.closest("[data-t]"); if (!t) return;
    const o = selected, name = t.dataset.t;
    if (name === "nofill") { if (o) { push(); o.fill = ""; renderObjects(o.page); } else style.fill = ""; }
    else if (o) { push(); o[name] = !o[name]; renderObjects(o.page); }
    else style[name] = !style[name];
    paintProps(); saveDraft();
  });

  // ------------------------------------------------------------------ page actions
  pagesEl.addEventListener("click", e => {
    const b = e.target.closest("[data-pa]"); if (!b) return;
    const key = b.closest(".ed-pagewrap").dataset.key, idx = pages.findIndex(p => p.key === key), p = pages[idx];
    push();
    if (b.dataset.pa === "rotl" || b.dataset.pa === "rotr") {
      if (objects.some(o => o.page === key)) { history.pop(); return toast("Rotate pages before adding anything to them", "err"); }
      p.rot = (p.rot + (b.dataset.pa === "rotr" ? 90 : 270)) % 360;
    }
    if (b.dataset.pa === "del") {
      if (pages.length === 1) { history.pop(); return toast("A document needs at least one page", "err"); }
      pages.splice(idx, 1); objects = objects.filter(o => o.page !== key);
    }
    if (b.dataset.pa === "ins") { const s = size(p); pages.splice(idx + 1, 0, { key: "n" + Date.now(), orig: -1, rot: 0, base: 0, w: s.w, h: s.h }); }
    renderAll(); saveDraft();
  });

  // ------------------------------------------------------------------ pointer interactions
  let drag = null;
  pagesEl.addEventListener("pointerdown", e => {
    const pageEl = e.target.closest(".ed-page"); if (!pageEl || e.button !== 0) return;
    const key = pageEl.closest(".ed-pagewrap").dataset.key;
    const pt = toPt(e, pageEl);
    const objNode = e.target.closest(".obj");
    if (e.target.closest("[data-object-action]")) return;
    if (e.target.closest("[data-del]")) { const o = byId(objNode.dataset.id); if (o) remove(o); return; }
    if (objNode) {
      const o = byId(objNode.dataset.id);
      const editing = e.target.closest("[contenteditable]") && document.activeElement === e.target.closest("[contenteditable]");
      if (editing) return;
      if (selected !== o) select(o, false);
      const handle = e.target.closest("[data-handle]");
      drag = { mode: handle ? "resize" : "move", o, start: pt, orig: JSON.parse(JSON.stringify(o)), pageEl, moved: false, tw: Math.max(10, objNode.offsetWidth / zoom) };
      pageEl.setPointerCapture(e.pointerId);
      if (!e.target.closest("[contenteditable]")) e.preventDefault();
      return;
    }
    if (selected) { const prev = selected; selected = null; renderObjects(prev.page); paintProps(); dropIfEmpty(prev); }
    if (tool === "select" || tool === "edittext") return;
    e.preventDefault();
    if (tool === "text") { createText(key, pt); return; }
    if (tool === "sign" || tool === "image") { placeImage(key, pt); return; }
    if (tool === "field-check" || tool === "field-radio") {
      push();
      const radio = tool === "field-radio", prior = objects.filter(o => o.kind === "radio").at(-1);
      const o = add({ type: "field", kind: radio ? "radio" : "checkbox", page: key, x: pt.x - 7, y: pt.y - 7, w: 14, h: 14,
        name: radio ? prior?.name || nextFieldName("radio") : nextFieldName("check"), value: false,
        ...(radio ? { exportValue: "Option" + (objects.filter(o => o.kind === "radio").length + 1) } : {}) });
      select(o); return;
    }
    const draft = document.createElement("div");
    if (tool === "draw" || tool === "line" || tool === "arrow") {
      draft.className = "ed-draft"; draft.style.border = "0"; draft.style.background = "none";
      draft.style.inset = "0"; draft.innerHTML = `<svg style="position:absolute;inset:0;width:100%;height:100%"><polyline fill="none" stroke="${style.stroke}" stroke-width="${style.width * zoom}" stroke-linecap="round" stroke-linejoin="round" points=""/></svg>`;
    } else draft.className = "ed-draft";
    pageEl.appendChild(draft);
    drag = { mode: "create", start: pt, pts: [pt.x, pt.y], key, pageEl, draft };
    pageEl.setPointerCapture(e.pointerId);
  });

  pagesEl.addEventListener("click", async e => {
    const button = e.target.closest("[data-object-action]"); if (!button) return;
    const o = byId(button.closest(".obj").dataset.id); if (!o || !o.signature) return;
    e.stopPropagation();
    if (button.dataset.objectAction === "delete") return remove(o);
    if (button.dataset.objectAction === "duplicate") {
      push(); const copy = JSON.parse(JSON.stringify(o)); delete copy.id;
      const page = size(pages.find(p => p.key === o.page));
      copy.x = clamp(o.x + 15, 0, Math.max(0, page.w - o.w)); copy.y = clamp(o.y + 15, 0, Math.max(0, page.h - o.h));
      return select(add(copy));
    }
    try {
      const img = await loadImg(o.src), canvas = document.createElement("canvas"); canvas.width = img.height; canvas.height = img.width;
      const ctx = canvas.getContext("2d"); ctx.translate(canvas.width / 2, canvas.height / 2); ctx.rotate(Math.PI / 2); ctx.drawImage(img, -img.width / 2, -img.height / 2);
      if (!objects.includes(o)) return;
      push(); const center = { x: o.x + o.w / 2, y: o.y + o.h / 2 }, w = o.w; o.w = o.h; o.h = w;
      const page = size(pages.find(p => p.key === o.page)); o.x = clamp(center.x - o.w / 2, 0, Math.max(0, page.w - o.w)); o.y = clamp(center.y - o.h / 2, 0, Math.max(0, page.h - o.h));
      o.src = canvas.toDataURL("image/png"); renderObjects(o.page); paintProps(); saveDraft();
    } catch { toast("Could not rotate this signature.", "err"); }
  });

  pagesEl.addEventListener("pointermove", e => {
    if (!drag) return;
    const pt = toPt(e, drag.pageEl);
    const p = pages.find(x => x.key === (drag.key || drag.o?.page)); const lim = size(p);
    if (drag.mode === "create") {
      if (tool === "draw") { drag.pts.push(pt.x, pt.y); }
      else if (tool === "line" || tool === "arrow") { drag.pts = [drag.start.x, drag.start.y, pt.x, pt.y]; }
      else {
        const r = rect(drag.start, pt);
        Object.assign(drag.draft.style, { left: r.x * zoom + "px", top: r.y * zoom + "px", width: r.w * zoom + "px", height: r.h * zoom + "px" });
        return;
      }
      drag.draft.querySelector("polyline").setAttribute("points", chunk(drag.pts).map(([x, y]) => `${x * zoom},${y * zoom}`).join(" "));
      return;
    }
    const dx = pt.x - drag.start.x, dy = pt.y - drag.start.y;
    if (!drag.moved && Math.hypot(dx, dy) < 1.5) return;
    if (!drag.moved) { push(); drag.moved = true; }
    const o = drag.o, s = drag.orig;
    if (drag.mode === "move") {
      const ow = s.w || drag.tw || 20, oh = s.h || s.size * 1.2 || 20; // text objects have no w/h
      o.x = clamp(s.x + dx, -ow + 5, lim.w - 5); o.y = clamp(s.y + dy, -oh + 5, lim.h - 5);
      const ddx = o.x - s.x, ddy = o.y - s.y;
      if (o.area) o.area = { ...s.area, x: s.area.x + ddx, y: s.area.y + ddy };
      if (o.type === "line") Object.assign(o, { x1: s.x1 + ddx, y1: s.y1 + ddy, x2: s.x2 + ddx, y2: s.y2 + ddy });
      if (o.type === "draw") o.strokes = s.strokes.map(st => st.map((v, i) => v + (i % 2 ? ddy : ddx)));
    } else if (o.type === "text") { // the corner handle scales the font
      o.size = round2(clamp(s.size * Math.max(0.05, (drag.tw + dx) / drag.tw), 4, 200));
    } else {
      let w = Math.max(6, s.w + dx), h = Math.max(6, s.h + dy);
      if (o.type === "image" && !e.shiftKey) h = w * (s.h / s.w);
      o.w = w; o.h = h;
    }
    renderObjects(o.page);
  });

  pagesEl.addEventListener("pointerup", e => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.mode !== "create") { if (d.moved) { saveDraft(); if (d.mode === "resize") paintProps(); } return; }
    d.draft.remove();
    const pt = toPt(e, d.pageEl);
    let r = rect(d.start, pt);
    const tiny = r.w < 4 && r.h < 4;
    push();
    let o = null;
    if (tool === "draw") {
      if (d.pts.length < 4) { history.pop(); return; }
      const xs = d.pts.filter((_, i) => i % 2 === 0), ys = d.pts.filter((_, i) => i % 2 === 1);
      const last = objects.find(x => x.type === "draw" && x.page === d.key && x._live && x.color === style.stroke && x.width === style.width);
      if (last) {
        last.strokes.push(d.pts.map(round2));
        const all = last.strokes.flat(); const ax = all.filter((_, i) => i % 2 === 0), ay = all.filter((_, i) => i % 2 === 1);
        Object.assign(last, { x: Math.min(...ax), y: Math.min(...ay), w: Math.max(...ax) - Math.min(...ax), h: Math.max(...ay) - Math.min(...ay) });
        renderObjects(d.key); saveDraft(); return;
      }
      o = add({ type: "draw", page: d.key, strokes: [d.pts.map(round2)], color: style.stroke, width: style.width, _live: true,
        x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) });
      return;
    }
    if (tool === "line" || tool === "arrow") {
      const [x1, y1, x2, y2] = d.pts.length === 4 ? d.pts : [d.start.x, d.start.y, d.start.x + 80, d.start.y];
      o = add({ type: "line", kind: tool, page: d.key, x1, y1, x2, y2, x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), color: style.stroke, width: style.width });
    } else if (tool === "whiteout" || tool === "rect" || tool === "ellipse") {
      if (tiny) r = { x: d.start.x - 40, y: d.start.y - 15, w: 80, h: 30 };
      o = tool === "whiteout"
        ? add({ type: "shape", shape: "rectangle", page: d.key, ...r, fill: "#ffffff", stroke: "#ffffff", strokeWidth: 0, whiteout: true })
        : add({ type: "shape", shape: tool === "ellipse" ? "ellipse" : "rectangle", page: d.key, ...r, fill: style.fill, stroke: style.stroke, strokeWidth: style.width });
    } else if (["highlight", "strike", "underline"].includes(tool)) {
      if (tiny) { history.pop(); return toast("Drag across the text to mark it"); }
      o = add({ type: "mark", kind: { highlight: "highlight", strike: "strikethrough", underline: "underline" }[tool], page: d.key, ...r, color: tool === "highlight" ? style.mark : "#e03131" });
    } else if (tool === "link") {
      if (tiny) r = { x: d.start.x - 50, y: d.start.y - 10, w: 100, h: 20 };
      dialog({ title: "Link to", text: "A web address, e-mail, phone number, or a page number in this document.", fields: [{ name: "href", placeholder: "https://… or 3" }], ok: "Add link" }).then(v => {
        if (!v?.href?.trim()) { history.pop(); return; }
        let href = v.href.trim();
        if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(href)) href = "mailto:" + href;
        else if (/^\+?[\d\s()-]{6,}$/.test(href) && !/^\d{1,4}$/.test(href)) href = "tel:" + href.replace(/\s/g, "");
        select(add({ type: "link", page: d.key, ...r, href }));
      });
      return;
    } else if (["field-text", "field-dropdown", "field-listbox"].includes(tool)) {
      const kind = tool.slice(6);
      if (tiny) r = { x: d.start.x, y: d.start.y - 10, w: 160, h: kind === "listbox" ? 60 : 20 };
      o = add({ type: "field", kind, page: d.key, ...r, name: nextFieldName(kind), multiline: kind === "text" && r.h > 40,
        value: "", ...(kind !== "text" ? { options: ["Option 1", "Option 2"] } : {}) });
    }
    if (o) select(o);
  });

  function toPt(e, pageEl) { const b = pageEl.getBoundingClientRect(); return { x: (e.clientX - b.left) / zoom, y: (e.clientY - b.top) / zoom }; }
  function rect(a, b) { return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) }; }
  function byId(id) { return objects.find(o => o.id == id); }
  function nextFieldName(prefix) { let n = 1; const names = new Set([...pdfFieldNames, ...objects.filter(o => o.type === "field").map(o => o.name)]); while (names.has(`${prefix}${n}`)) n++; return `${prefix}${n}`; }

  function createText(key, pt) {
    push();
    let text = "";
    if (style._dateNext) { text = new Date().toLocaleDateString(); style._dateNext = false; }
    const o = add({ type: "text", page: key, x: pt.x, y: pt.y - style.size * 0.6, text, _snap: text, font: style.font, size: style.size, color: style.color, bold: style.bold, italic: style.italic });
    select(o, true);
  }

  function placeImage(key, pt) {
    if (!pendingImage) return toast("Choose an image first");
    push();
    const w = pendingImage.sig ? 160 : Math.min(240, size(pages.find(p => p.key === key)).w * 0.5);
    const h = w / (pendingImage.ratio || 1);
    const o = add({ type: "image", page: key, x: pt.x - w / 2, y: pt.y - h / 2, w, h, src: pendingImage.src, signature: !!pendingImage.sig, opacity: 1 });
    select(o);
    if (!pendingImage.sig) { pendingImage = null; setTool("select"); }
  }

  document.addEventListener("keydown", e => {
    if (ed.hidden) return;
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); undo(); }
    if ((e.key === "Delete" || e.key === "Backspace") && selected && !typing) { e.preventDefault(); remove(selected); }
    if (e.key === "Escape" && !typing) setTool("select");
  });

  function loadImg(src) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; }); }
  async function fileToDataUrl(f, max, whiteToAlpha = false) {
    const url = URL.createObjectURL(f);
    try {
      const img = await loadImg(url);
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas"); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const x = c.getContext("2d"); x.drawImage(img, 0, 0, c.width, c.height);
      if (whiteToAlpha) {
        const d = x.getImageData(0, 0, c.width, c.height);
        for (let i = 0; i < d.data.length; i += 4) { const v = (d.data[i] + d.data[i + 1] + d.data[i + 2]) / 3; if (v > 215) d.data[i + 3] = 0; }
        x.putImageData(d, 0, 0);
      }
      const png = whiteToAlpha || /png|gif|webp/.test(f.type);
      return { dataUrl: c.toDataURL(png ? "image/png" : "image/jpeg", 0.9), ratio: c.width / c.height };
    } finally { URL.revokeObjectURL(url); }
  }

  // ------------------------------------------------------------------ save
  function buildBody() {
    const ops = { appendTextOperations: [], editTextOperations: [], imageOperations: [], shapeOperations: [], highlightTextOperations: [],
      appendDraw: [], appendLine: [], appendLinkOperations: [], appendFormFieldOperations: [] };
    for (const o of objects) {
      const pi = pages.findIndex(p => p.key === o.page); if (pi < 0) continue;
      const H = size(pages[pi]).h, page = String(pi + 1);
      const flip = (y, h = 0) => round2(H - y - h);
      if (o.type === "text") {
        if (!o.text.trim()) continue;
        ops.appendTextOperations.push({ text: o.text, font: o.font, fontSize: o.size.toFixed(2), position: { x: round2(o.x), y: flip(o.y + o.size * baseK(o)) },
          lineHeight: round2(o.size * 1.2), color: o.color, bold: !!o.bold, italic: !!o.italic, pages: page });
      } else if (o.type === "edittext") {
        const a = o.area;
        ops.editTextOperations.push({ page, area: { x: round2(a.x), y: flip(a.y, a.h), width: round2(a.w), height: round2(a.h) }, text: o.text,
          font: o.font, fontSize: o.size.toFixed(2), color: o.color, bold: !!o.bold, italic: !!o.italic,
          position: { x: round2(o.x), y: flip(o.y + o.size * baseK(o)) }, lineHeight: round2(o.size * 1.2) });
      } else if (o.type === "image") {
        ops.imageOperations.push({ pages: page, position: { x: round2(o.x), y: flip(o.y, o.h) }, width: round2(o.w), height: round2(o.h), image: o.src, rotation: 0, opacity: o.opacity ?? 1 });
      } else if (o.type === "shape") {
        // on screen the border is drawn inside the box; PDF strokes are centred on the path, so inset by half the width
        const bw = Math.min(o.strokeWidth || 0, o.w, o.h), ins = bw / 2;
        ops.shapeOperations.push({ pages: page, position: { x: round2(o.x + ins), y: flip(o.y + ins, o.h - bw) }, width: round2(o.w - bw), height: round2(o.h - bw), shape: o.shape,
          borderWidth: o.strokeWidth || 0, borderColor: o.strokeWidth ? o.stroke : null, backgroundColor: o.fill || null });
      } else if (o.type === "mark") {
        ops.highlightTextOperations.push({ page, kind: o.kind, color: o.color, boundingBoxes: [{ left: round2(o.x), right: round2(o.x + o.w), top: flip(o.y), bottom: flip(o.y, o.h) }] });
      } else if (o.type === "line") {
        ops.appendLine.push({ page, kind: o.kind, color: o.color, lineSize: o.width, points: [round2(o.x1), flip(o.y1), round2(o.x2), flip(o.y2)] });
      } else if (o.type === "draw") {
        ops.appendDraw.push({ page, color: o.color, lineSize: o.width, inklist: o.strokes.map(s => s.map((v, i) => i % 2 ? flip(v) : round2(v))) });
      } else if (o.type === "link") {
        const isPage = /^\d+$/.test(o.href);
        ops.appendLinkOperations.push({ page, kind: isPage ? "page" : "uri", href: o.href, boundingBoxes: [{ left: round2(o.x), right: round2(o.x + o.w), top: flip(o.y), bottom: flip(o.y, o.h) }] });
      } else if (o.type === "field") {
        ops.appendFormFieldOperations.push({ page, kind: o.kind, name: o.name, multiline: !!o.multiline, required: !!o.required,
          value: o.value ?? "", ...(o.maxLength ? { maxLength: o.maxLength } : {}), comb: !!o.comb,
          ...(o.options ? { options: o.options } : {}), multiSelect: !!o.multiSelect, ...(o.exportValue ? { exportValue: o.exportValue } : {}),
          boundingBox: { left: round2(o.x), right: round2(o.x + o.w), top: flip(o.y), bottom: flip(o.y, o.h) } });
      }
    }
    const body = { type: cfg.type, files: [file.id], pageOrder: pages.map(p => p.orig === -1 ? `-1:${p.rot}:${round2(p.w)}x${round2(p.h)}` : `${p.orig}:${p.rot}`), ...ops, uri: location.pathname };
    if (Object.keys(formValues).length) body.formValues = formValues;
    if ($("#ed-flatten").checked) body.flattenForms = true;
    return body;
  }

  ed.querySelector(".ed-footer").addEventListener("click", async e => {
    const b = e.target.closest("[data-action]"); if (!b) return;
    if (b.dataset.action === "close") {
      if (hasChanges() && !(await dialog({ title: "Discard your changes?", text: "Everything you added will be lost.", ok: "Discard" }))) return;
      clearDraft(); Tool.reset();
    }
    if (b.dataset.action === "save") {
      document.activeElement?.blur?.();
      const body = buildBody();
      if (!hasChanges()) return toast("Make a change first");
      b.disabled = true;
      const savedKey = draftKey(), snapshot = persistDraft();
      await Tool.submitBody(body, { onCompleted: () => {
        // Clear only this saved revision after the server has produced a result.
        try { if (localStorage.getItem(savedKey) === snapshot) { localStorage.removeItem(savedKey); draftDirty = false; } } catch {}
      } });
      b.disabled = false;
    }
  });

  // ------------------------------------------------------------------ crash recovery (this device only)
  const draftKey = () => draftIdentity ? `editorDraft:v2:${draftIdentity}` : null;
  let draftTimer = null, draftIdentity = null, draftDirty = false;
  const hasChanges = () => meaningful().length || Object.keys(formValues).length ||
    pages.length !== doc.numPages || pages.some((p, i) => p.orig !== i + 1 || p.rot);
  function persistDraft() {
    clearTimeout(draftTimer);
    const key = draftKey();
    if (!key) return null;
    const snapshot = JSON.stringify({ at: Date.now(), pages, objects, formValues });
    try { localStorage.setItem(key, snapshot); } catch { /* editing works without storage */ }
    return snapshot;
  }
  function saveDraft() {
    draftDirty = true;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(persistDraft, 800);
  }
  function clearDraft() { clearTimeout(draftTimer); draftDirty = false; try { localStorage.removeItem(draftKey()); } catch {} }
  function pruneDrafts() {
    try {
      for (const key of Object.keys(localStorage).filter(key => key.startsWith("editorDraft:v2:"))) {
        let draft = null;
        try { draft = JSON.parse(localStorage.getItem(key)); } catch {}
        if (!draft || !Number.isFinite(draft.at) || Date.now() - draft.at > 48 * 3600e3 || !Array.isArray(draft.pages) || !Array.isArray(draft.objects)) localStorage.removeItem(key);
      }
    } catch { /* storage may be unavailable */ }
  }
  window.addEventListener("pagehide", () => { if (draftDirty && doc && draftKey() && hasChanges()) persistDraft(); });
  async function offerRecovery() {
    let d = null;
    try { d = JSON.parse(localStorage.getItem(draftKey()) || "null"); } catch {}
    if (!d || !Array.isArray(d.pages) || !d.pages.length || !Array.isArray(d.objects) ||
      !Number.isFinite(d.at) || Date.now() - d.at > 48 * 3600e3) return;
    const keys = new Set(d.pages.map(p => p?.key));
    if (keys.size !== d.pages.length || d.pages.some(p => !p || typeof p.key !== "string" || !Number.isInteger(p.orig) ||
      (p.orig !== -1 && (p.orig < 1 || p.orig > doc.numPages)) || ![0, 90, 180, 270].includes(p.rot) ||
      (p.orig === -1 ? !(p.w > 0 && p.h > 0) : !Array.isArray(p.view))) ||
      d.objects.some(o => !o || !keys.has(o.page) || !Number.isInteger(o.id))) return;
    const structural = d.pages.length !== doc.numPages || d.pages.some((p, i) => p.orig !== i + 1 || p.rot);
    if (!structural && !d.objects.length && !Object.keys(d.formValues || {}).length) return;
    const v = await dialog({ title: "Recover unsaved changes?", text: `You edited this file before (${new Date(d.at).toLocaleString()}) without saving.`, ok: "Recover", cancel: "Start fresh" });
    if (v) { pages = d.pages; objects = d.objects; formValues = d.formValues || {}; draftDirty = true; idSeq = Math.max(1, ...objects.map(o => o.id + 1)); }
    else clearDraft();
  }

  // ------------------------------------------------------------------ blank document
  document.addEventListener("click", e => {
    if (!e.target.closest('[data-action="blank"]')) return;
    $("#upload-menu").hidden = true;
    Tool.addFiles([new File([blankPdf()], "document.pdf", { type: "application/pdf" })]);
  });
  function blankPdf() {
    const objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << >> >>"];
    let out = "%PDF-1.4\n", offs = [];
    objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const x = out.length;
    out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, "0") + " 00000 n \n").join("");
    out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
    return out;
  }
})();
