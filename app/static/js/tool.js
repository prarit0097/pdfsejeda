/* Tool page controller: upload -> options -> POST /api/tasks -> poll /change -> result.
 * Shared state lives in window.Tool so pages-ui.js (thumbnails) can read files and add params. */
(() => {
  const { $, icon, toast, dialog, fmtSize, esc } = window.UI;
  const cfg = JSON.parse($("#tool-config").textContent);
  const CHUNK = 5 * 1024 * 1024;
  const form = $("#task-form"), list = $("#file-list"), uploadStage = $("#stage-upload"), resultStage = $("#stage-result");
  const input = $("#file-input");
  let localCounter = 0;

  const Tool = window.Tool = {
    cfg,
    files: [],               // {localId, id, name, size, pages, passwordProtected, status, progress, rotation, error}
    extraParams: () => ({}), // pages-ui.js replaces this
    validators: [],          // functions returning an error string or ""
    emit() { document.dispatchEvent(new CustomEvent("files-changed", { detail: Tool.files })); },
    readyFiles() { return Tool.files.filter(f => f.status === "ready"); },
  };

  // ---------- upload ----------
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-action]");
    if (!a) return;
    const act = a.dataset.action;
    if (act === "pick") { $("#upload-menu").hidden = true; input.click(); }
    if (act === "upload-menu") { e.stopPropagation(); $("#upload-menu").hidden = !$("#upload-menu").hidden; }
    if (act === "url") { $("#upload-menu").hidden = true; askUrl(); }
    if (act === "reset") resetAll();
    if (act === "more") {
      const more = $("#more-opts"), open = a.getAttribute("aria-expanded") !== "true";
      a.setAttribute("aria-expanded", open); more.hidden = !open;
    }
  });
  document.addEventListener("click", e => { const m = $("#upload-menu"); if (m && !m.hidden && !e.target.closest(".split-btn")) m.hidden = true; });
  input?.addEventListener("change", () => { addFiles([...input.files]); input.value = ""; });

  ["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault(); uploadStage?.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => {
    if (ev === "dragleave" && e.relatedTarget) return;
    uploadStage?.classList.remove("drag");
  }));
  document.addEventListener("drop", e => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault(); addFiles([...e.dataTransfer.files]);
  });
  document.addEventListener("paste", e => {
    const fs = [...(e.clipboardData?.files || [])];
    if (fs.length && !e.target.closest("input, textarea")) addFiles(fs);
  });

  function extOk(name) {
    const ext = name.split(".").pop().toLowerCase();
    return cfg.accept.includes(ext);
  }

  function addFiles(fileObjs) {
    if (!fileObjs.length) return;
    if (!cfg.multiple) { Tool.files = []; fileObjs = fileObjs.slice(0, 1); }
    for (const f of fileObjs) {
      if (!extOk(f.name)) { toast(`“${f.name}” isn't a supported file type here`, "err"); continue; }
      if (f.size > cfg.maxFileMb * 1048576) { toast(`“${f.name}” is larger than ${cfg.maxFileMb} MB`, "err"); continue; }
      if (Tool.files.length >= cfg.maxFiles) { toast(`At most ${cfg.maxFiles} files`, "err"); break; }
      const entry = { localId: ++localCounter, name: f.name, size: f.size, status: "uploading", progress: 0, rotation: 0, blob: f };
      Tool.files.push(entry);
      upload(entry);
    }
    showWork(); render();
  }

  Tool.addFiles = files => addFiles(files);

  async function upload(entry) {
    try {
      const info = entry.blob.size > CHUNK ? await uploadChunked(entry) : await uploadSimple(entry);
      Object.assign(entry, info, { status: "ready", progress: 100 });
      if (info.passwordProtected) await askPassword(entry);
    } catch (err) {
      entry.status = "error"; entry.error = err.message || "Upload failed";
    }
    render(); Tool.emit();
  }

  function xhrPost(url, body, headers, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", url);
      Object.entries(headers || {}).forEach(([k, v]) => x.setRequestHeader(k, v));
      x.upload.onprogress = e => e.lengthComputable && onProgress?.(e.loaded, e.total);
      x.onload = () => {
        if (x.status >= 200 && x.status < 300) { try { resolve(JSON.parse(x.responseText)); } catch { resolve({}); } }
        else reject(new Error(x.responseText || `Upload failed (${x.status})`));
      };
      x.onerror = () => reject(new Error("Network error during upload"));
      x.send(body);
    });
  }

  function uploadSimple(entry) {
    const fd = new FormData(); fd.append("file", entry.blob, entry.name);
    return xhrPost("/api/files/upload", fd, { "X-FileLocalId": String(entry.localId) }, (l, t) => { entry.progress = l / t * 100; renderProgress(entry); });
  }

  async function uploadChunked(entry) {
    const size = entry.blob.size, uploadId = crypto.randomUUID().replace(/-/g, "");
    let done = 0, result = null;
    const starts = []; for (let s = 0; s < size; s += CHUNK) starts.push(s);
    async function send(start) {
      const end = Math.min(start + CHUNK, size) - 1;
      const fd = new FormData(); fd.append("file", entry.blob.slice(start, end + 1), entry.name);
      const r = await xhrPost("/api/files/upload-chunked", fd, {
        "Content-Range": `bytes ${start}-${end}/${size}`, "X-Upload-Id": uploadId, "X-File-Name": encodeURIComponent(entry.name),
      });
      done += end - start + 1; entry.progress = done / size * 100; renderProgress(entry);
      if (r.id) result = r;
    }
    const last = starts.pop();
    const pool = [...starts];
    await Promise.all(Array.from({ length: 3 }, async () => { while (pool.length) await send(pool.shift()); }));
    await send(last); // the final chunk completes the file
    if (!result) throw new Error("Upload did not complete");
    return result;
  }

  async function askUrl() {
    const v = await dialog({ title: "Add from a web address", text: "Paste a direct link to a file.", fields: [{ name: "url", placeholder: "https://example.com/file.pdf", type: "url", required: true }], ok: "Add" });
    if (!v?.url) return;
    let url = v.url.trim();
    if (/^(file:|[a-z]:\\|\\)/i.test(url)) return toast("Local paths can't be used. Upload the file instead.", "err");
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    try { if (new URL(url).host === location.host) return toast("That link points to this site. Please use a link to the file itself.", "err"); }
    catch { return toast("That doesn't look like a valid web address", "err"); }
    if (!cfg.multiple) Tool.files = [];
    const entry = { localId: ++localCounter, name: decodeURIComponent(url.split("/").pop().split("?")[0] || "file"), status: "uploading", progress: 30, rotation: 0 };
    Tool.files.push(entry); showWork(); render();
    try {
      const r = await fetch("/api/files", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
      if (!r.ok) throw new Error(await r.text());
      Object.assign(entry, await r.json(), { status: "ready", progress: 100 });
      if (!extOk(entry.name)) toast(`“${entry.name}” may not be supported by this tool`, "err");
      if (entry.passwordProtected) await askPassword(entry);
    } catch (err) { entry.status = "error"; entry.error = err.message; }
    render(); Tool.emit();
  }

  async function askPassword(entry) {
    for (;;) {
      const v = await dialog({ title: "Password required", text: `“${entry.name}” is protected. Enter its password to continue.`, fields: [{ name: "password", type: "password", label: "Password", required: true }], ok: "Unlock" });
      if (!v) { entry.status = "error"; entry.error = "Password needed"; return; }
      const r = await fetch(`/api/files/${entry.id}/password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: v.password }) });
      if (r.ok) { const j = await r.json(); entry.pages = j.pages; entry.passwordProtected = false; entry.password = v.password; return; }
      toast(await r.text(), "err");
    }
  }

  // ---------- file list ----------
  function showWork() {
    if (!Tool.files.length) return;
    uploadStage.hidden = true; resultStage.hidden = true;
    if (cfg.editor) document.dispatchEvent(new CustomEvent("editor-open"));
    else form.hidden = false;
  }

  function resetAll() {
    Tool.files = []; render(); Tool.emit();
    document.dispatchEvent(new CustomEvent("editor-close"));
    form.hidden = true; resultStage.hidden = true; uploadStage.hidden = false;
    history.replaceState(null, "", location.pathname);
  }

  function render() {
    if (!list) return;
    const sortable = cfg.pageUi === "files" && Tool.files.length > 1;
    $("#files-title").textContent = Tool.files.length === 1 ? "1 file" : `${Tool.files.length} files`;
    list.innerHTML = Tool.files.map(f => `
      <li class="file-item" data-local="${f.localId}" ${sortable ? 'draggable="true"' : ""}>
        ${sortable ? `<span class="handle" title="Drag to reorder">${icon("drag")}</span>` : ""}
        <span class="tool-ico" style="width:38px;height:38px;--c:var(--cat-${f.status === "error" ? "edit" : "organize"})">${icon(/\.pdf$/i.test(f.name) ? "file" : "image")}</span>
        <div class="grow">
          <div class="name" title="${esc(f.name)}">${esc(f.name)}</div>
          <div class="meta">${f.status === "uploading" ? "Uploading…" : f.status === "error" ? `<span class="badge badge-err">${esc(f.error)}</span>` :
            [fmtSize(f.size), f.pages ? `${f.pages} page${f.pages > 1 ? "s" : ""}` : "", f.rotation ? `rotated ${f.rotation}°` : ""].filter(Boolean).join(" · ")}</div>
          ${f.status === "uploading" ? `<div class="progress"><i style="width:${f.progress}%"></i></div>` : ""}
        </div>
        ${cfg.pageUi === "files" && f.status === "ready" ? `<button class="icon-btn" type="button" data-rotate title="Rotate">${icon("rotate")}</button>` : ""}
        <button class="icon-btn" type="button" data-remove title="Remove">${icon("x")}</button>
      </li>`).join("");
    if (!Tool.files.length && !form.hidden) resetAll();
  }

  function renderProgress(entry) {
    const bar = list?.querySelector(`[data-local="${entry.localId}"] .progress > i`);
    if (bar) bar.style.width = entry.progress + "%";
  }

  list?.addEventListener("click", e => {
    const li = e.target.closest(".file-item"); if (!li) return;
    const f = Tool.files.find(x => x.localId == li.dataset.local);
    if (e.target.closest("[data-remove]")) { Tool.files = Tool.files.filter(x => x !== f); render(); Tool.emit(); }
    if (e.target.closest("[data-rotate]")) { f.rotation = (f.rotation + 90) % 360; render(); }
  });
  let dragEl = null;
  list?.addEventListener("dragstart", e => { dragEl = e.target.closest(".file-item"); dragEl?.classList.add("dragging"); });
  list?.addEventListener("dragend", () => { dragEl?.classList.remove("dragging"); dragEl = null; });
  list?.addEventListener("dragover", e => {
    if (!dragEl) return; e.preventDefault();
    const over = e.target.closest(".file-item"); if (!over || over === dragEl) return;
    const after = e.clientY > over.getBoundingClientRect().top + over.offsetHeight / 2;
    over.parentNode.insertBefore(dragEl, after ? over.nextSibling : over);
  });
  list?.addEventListener("drop", e => {
    if (!dragEl) return; e.preventDefault();
    const order = [...list.children].map(li => li.dataset.local);
    Tool.files.sort((a, b) => order.indexOf(String(a.localId)) - order.indexOf(String(b.localId)));
    render(); Tool.emit();
  });

  // ---------- conditional options ----------
  function syncShowIf() {
    document.querySelectorAll("[data-show-if]").forEach(el => {
      const cond = JSON.parse(el.dataset.showIf);
      const on = Object.entries(cond).every(([name, want]) => {
        const v = fieldValue(name);
        return Array.isArray(want) ? want.map(String).includes(String(v)) : String(v) === String(want);
      });
      el.hidden = !on;
    });
  }
  function fieldValue(name) {
    const els = form.querySelectorAll(`[name="${name}"]`);
    for (const el of els) {
      if (el.type === "radio") { if (el.checked) return el.value; }
      else if (el.type === "checkbox") return el.checked ? "true" : "false";
      else return el.value;
    }
    return "";
  }
  form?.addEventListener("change", syncShowIf);
  form?.addEventListener("input", syncShowIf);
  syncShowIf();

  // ---------- submit ----------
  function collect() {
    const body = { type: cfg.type };
    form.querySelectorAll("[name]").forEach(el => {
      if (el.closest("[hidden]") && el.type !== "hidden") return;
      const n = el.name; if (n === "type") return;
      if (el.type === "radio") { if (el.checked) body[n] = el.value; return; }
      if (el.type === "checkbox") { body[n] = el.checked; return; }
      if (el.type === "number") { body[n] = el.value === "" ? "" : Number(el.value); return; }
      if (el.type === "file") return;
      if (n.endsWith("[]")) { (body[n.slice(0, -2)] ||= []).push(el.value); return; }
      body[n] = el.value;
    });
    const ready = Tool.readyFiles();
    body.files = ready.map(f => f.id);
    if (cfg.pageUi === "files") body.rotations = ready.map(f => f.rotation || 0);
    Object.assign(body, Tool.extraParams(body));
    body.uri = location.pathname;
    return body;
  }

  let submitting = false;
  form?.addEventListener("submit", e => {
    e.preventDefault();
    if (Tool.files.some(f => f.status === "uploading")) return toast("Please wait until the uploads finish");
    const ready = Tool.readyFiles();
    if (cfg.type !== "htmlToPdf" && ready.length < cfg.minFiles) return toast(cfg.minFiles > 1 ? `Please add at least ${cfg.minFiles} files` : "Please add a file first", "err");
    for (const v of Tool.validators) { const msg = v(); if (msg) return toast(msg, "err"); }
    submitBody(collect());
  });

  /** POST a task body and show the processing/result screen. Used by the form and by the editor. */
  async function submitBody(body) {
    if (submitting) return false;
    submitting = true;
    const btn = $("#submit-btn"); if (btn) btn.disabled = true;
    try {
      const r = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (r.status === 402) { const j = await r.json(); showQuota(Number(r.headers.get("x-ratelimit-wait") || 0), j.reason); return false; }
      if (r.status === 429) { toast("Too many attempts. Please try again in a little while.", "err"); return false; }
      if (!r.ok) { toast(await r.text() || "The server rejected this task", "err"); return false; }
      showProcessing(await r.json());
      return true;
    } catch { toast("You appear to be offline. Check your connection and try again.", "err"); return false; }
    finally { submitting = false; if (btn) btn.disabled = false; }
  }
  Tool.submitBody = submitBody;

  function showQuota(wait, reason) {
    resultStage.hidden = false;
    let left = wait;
    resultStage.innerHTML = `<div class="result"><div class="state-icon err">${icon("clock", "icon-lg")}</div>
      <h2>Hourly limit reached</h2><p class="muted">You've used all free tasks for this hour (${esc(reason)}). You can start a new task in <b id="quota-clock"></b>.</p></div>`;
    const tick = () => { const m = Math.floor(left / 60), s = left % 60; const el = $("#quota-clock"); if (el) el.textContent = `${m}:${String(s).padStart(2, "0")}`; if (left-- > 0) setTimeout(tick, 1000); };
    tick();
  }

  // ---------- results ----------
  function showProcessing(taskId) {
    form.hidden = true; resultStage.hidden = false;
    document.dispatchEvent(new CustomEvent("editor-close"));
    resultStage.innerHTML = `<div class="result"><div class="spinner"></div><h2>Working on it…</h2><p class="muted" id="proc-note">Your files are being processed.</p>
      <button class="btn btn-ghost btn-sm" type="button" id="cancel-btn">Cancel</button></div>`;
    $("#cancel-btn").onclick = async () => { await fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" }); backToForm(); };
    history.replaceState(null, "", `#results-${taskId}`);
    let polls = 0;
    const poll = async () => {
      polls++;
      try {
        const r = await fetch(`/api/tasks/${taskId}/change?_=${Date.now()}`);
        if (r.status === 404) return showFailed("These files have expired. Please upload them again.");
        const t = await r.json();
        const st = String(t.status).toLowerCase();
        if (st === "completed") return showCompleted(t);
        if (st === "failed") return showFailed(t.failureReason || "Processing failed");
        if (polls === 10) { const n = $("#proc-note"); if (n) n.textContent = "This is taking longer than usual. Large files can need up to a few minutes."; }
        setTimeout(poll, 3000);
      } catch { setTimeout(poll, 10000); }
    };
    setTimeout(poll, 600);
  }

  function urlFor(t, filename) {
    return `${location.protocol}//${t.resultFullUrlPattern}`.replaceAll(encodeURIComponent("{{filename}}"), encodeURIComponent(filename));
  }

  function showCompleted(t) {
    const dl = urlFor(t, t.resultFilename);
    const isPdf = /\.pdf$/i.test(t.resultFilename);
    const multi = (t.resultItems || []).length > 1;
    resultStage.innerHTML = `<div class="result">
      <div class="state-icon ok">${icon("check", "icon-lg")}</div>
      <h2>Your file is ready</h2>
      ${t.remark ? `<p class="muted">${esc(t.remark)}</p>` : ""}
      <div class="result-actions">
        <a class="btn btn-primary btn-lg" href="${dl}" download="${esc(t.resultFilename)}">${icon("download")} Download ${multi ? "all (ZIP)" : ""}</a>
        ${isPdf ? `<button class="btn btn-lg" type="button" id="preview-btn">${icon("eye")} Preview</button>` : ""}
      </div>
      <p class="muted small">${esc(t.resultFilename)} · ${fmtSize(t.resultFileSize)}</p>
      ${(t.warnings || []).length ? `<div class="warnings">${t.warnings.map(w => `<div class="alert alert-warn">${icon("alert")}<span>${esc(w)}</span></div>`).join("")}</div>` : ""}
      ${multi ? `<div class="result-items card">${t.resultItems.map(n => `<a href="${urlFor(t, n)}" download="${esc(n)}">${icon(/\.pdf$/i.test(n) ? "file" : "image")}<span style="flex:1">${esc(n)}</span>${icon("download")}</a>`).join("")}</div>` : ""}
      <div class="result-actions" style="margin-top:26px">
        <div style="position:relative"><button class="btn" type="button" id="continue-btn">${icon("workflow")} Continue in another tool ${icon("chevron")}</button>
          <div class="menu" id="continue-menu" hidden style="bottom:110%;left:0;max-height:320px;overflow:auto"></div></div>
        <button class="btn btn-ghost" type="button" id="edit-again">Change options</button>
        <button class="btn btn-ghost" type="button" id="start-over">Start over</button>
        <button class="btn btn-ghost" type="button" id="delete-btn" title="Delete the result from the server now">${icon("trash")} Delete now</button>
      </div>
      <div id="preview-slot"></div>
    </div>`;
    $("#preview-btn")?.addEventListener("click", () => {
      $("#preview-slot").innerHTML = `<iframe class="preview-frame" src="${dl.replace("d=true", "v=true")}" title="Preview"></iframe>`;
    });
    $("#start-over").onclick = resetAll;
    $("#edit-again").onclick = backToForm;
    $("#delete-btn").onclick = async () => { await fetch(`/api/tasks/${t.id}`, { method: "DELETE" }); toast("Deleted from the server"); removeRecent(t.id); resetAll(); };
    $("#continue-btn").onclick = e => { e.stopPropagation(); openContinueMenu(t); };
    addRecent(t, dl);
  }

  async function openContinueMenu(t) {
    const menu = $("#continue-menu");
    if (!menu.hidden) { menu.hidden = true; return; }
    if (!Tool.catalog) Tool.catalog = await (await fetch("/api/tools")).json();
    const ext = t.resultFilename.split(".").pop().toLowerCase();
    const multi = (t.resultItems || []).length > 1;
    const usable = Tool.catalog.filter(x => x.slug !== cfg.slug && x.accept.some(a => multi ? t.resultItems.some(n => n.toLowerCase().endsWith("." + a)) : a === ext));
    menu.innerHTML = usable.map(x => `<button type="button" data-slug="${x.slug}">${esc(x.title)}</button>`).join("") || `<span class="muted small" style="padding:8px">No tool accepts this file</span>`;
    menu.hidden = false;
    menu.onclick = async e => {
      const b = e.target.closest("[data-slug]"); if (!b) return;
      const r = await fetch(`/api/tasks/${t.id}/continue`, { method: "POST" });
      if (!r.ok) return toast("These files have expired", "err");
      sessionStorage.setItem("continueFiles", JSON.stringify(await r.json()));
      location.href = "/" + b.dataset.slug;
    };
    document.addEventListener("click", function off(ev) { if (!menu.contains(ev.target)) { menu.hidden = true; document.removeEventListener("click", off); } });
  }

  function showFailed(reason) {
    resultStage.innerHTML = `<div class="result"><div class="state-icon err">${icon("alert", "icon-lg")}</div>
      <h2>That didn't work</h2><p class="muted">${esc(reason)}</p>
      <div class="result-actions"><button class="btn btn-primary" type="button" id="retry">Back to options</button><button class="btn btn-ghost" type="button" id="start-over">Start over</button></div></div>`;
    $("#retry").onclick = backToForm; $("#start-over").onclick = resetAll;
  }

  function backToForm() {
    resultStage.hidden = true; history.replaceState(null, "", location.pathname);
    if (cfg.editor) document.dispatchEvent(new CustomEvent("editor-open")); else form.hidden = false;
  }
  Tool.reset = () => resetAll();

  // ---------- recent results (this device only) ----------
  const RECENT_KEY = "recentResults", TTL = 2 * 3600 * 1000 - 5 * 60 * 1000;
  function readRecent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").filter(r => Date.now() - r.at < TTL); } catch { return []; } }
  function writeRecent(items) { try { localStorage.setItem(RECENT_KEY, JSON.stringify(items.slice(0, 15))); } catch {} }
  function addRecent(t, url) { writeRecent([{ id: t.id, name: t.resultFilename, url, tool: cfg.title, at: Date.now() }, ...readRecent().filter(r => r.id !== t.id)]); renderRecent(); }
  function removeRecent(id) { writeRecent(readRecent().filter(r => r.id !== id)); renderRecent(); }
  function renderRecent() {
    const items = readRecent(), box = $("#recent");
    if (!box) return;
    box.hidden = !items.length;
    $("#recent-list").innerHTML = items.map(r => `<div class="recent-item">${icon("file")}<a href="${r.url}" download style="flex:1">${esc(r.name)}</a><span class="muted small">${esc(r.tool)} · ${Math.round((Date.now() - r.at) / 60000)} min ago</span></div>`).join("");
  }
  renderRecent();

  // ---------- keep uploads alive while the page is open ----------
  setInterval(() => Tool.readyFiles().forEach(f => fetch(`/api/files/${f.id}/touch`, { method: "POST" }).then(r => {
    if (r.status === 404) { f.status = "error"; f.error = "Expired — please upload again"; render(); Tool.emit(); }
  })), 10 * 60 * 1000);

  // ---------- files handed over from another tool ----------
  try {
    const handed = JSON.parse(sessionStorage.getItem("continueFiles") || "null");
    sessionStorage.removeItem("continueFiles");
    if (Array.isArray(handed) && handed.length) {
      const usable = handed.filter(f => extOk(f.name));
      (cfg.multiple ? usable : usable.slice(0, 1)).forEach(f => Tool.files.push({ ...f, localId: ++localCounter, status: "ready", progress: 100, rotation: 0 }));
      if (Tool.files.length) { showWork(); render(); setTimeout(() => Tool.emit(), 0); }
    }
  } catch {}
})();
