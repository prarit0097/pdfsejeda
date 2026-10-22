/* Workflows page: list saved chains (localStorage "workflows"), run one on uploaded files.
 * Each step is a task body recorded by tool.js (without files). Running = submit step 1 with the
 * uploaded file ids, wait, register its results as new files (/continue), submit step 2 with those, … */
(() => {
  const { $, icon, toast, dialog, esc } = window.UI;
  const Tool = window.Tool;
  const KEY = "workflows";
  const EXAMPLE = { id: "example", name: "Example: compress, then number the pages", created: 0, example: true, steps: [
    { type: "compress", uri: "/compress-pdf", title: "Compress PDF", imageQuality: "0.8", imageDpi: "144" },
    { type: "pageNumbers", uri: "/page-numbers-pdf", title: "Add page numbers", pattern: "[PAGE_ARABIC]", pageLocation: "bottom-center", fontSize: "10" },
  ] };
  let current = null;

  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } };
  const write = list => { try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { toast("Browser storage is full", "err"); } };

  function render() {
    const list = read();
    const all = list.length ? list : [EXAMPLE];
    $("#wf-list").innerHTML = all.map(w => `
      <div class="recent-item" data-id="${w.id}">
        <span class="tool-ico" style="--c:var(--cat-pages);width:38px;height:38px">${icon("workflow")}</span>
        <div style="flex:1;min-width:0"><div style="font-weight:600">${esc(w.name)}</div>
          <div class="muted small">${w.steps.map(s => esc(s.title || s.type)).join(" → ")}</div></div>
        <button class="btn btn-sm btn-primary" type="button" data-run>Use</button>
        ${w.example ? "" : `<button class="icon-btn" type="button" data-rename title="Rename">${icon("edit")}</button><button class="icon-btn" type="button" data-del title="Delete">${icon("trash")}</button>`}
      </div>`).join("") + (list.length ? "" : `<p class="muted small" style="padding:0 18px 14px">You have no saved workflows yet, so here is an example.</p>`);
  }

  $("#wf-list").addEventListener("click", async e => {
    const row = e.target.closest("[data-id]"); if (!row) return;
    const list = read(), w = list.find(x => x.id === row.dataset.id) || (row.dataset.id === "example" ? EXAMPLE : null);
    if (!w) return;
    if (e.target.closest("[data-run]")) {
      current = w;
      $("#wf-run").hidden = false;
      $("#wf-run-title").innerHTML = `<b>${esc(w.name)}</b>: ${w.steps.map(s => esc(s.title || s.type)).join(" → ")}`;
      $("#wf-run").scrollIntoView({ behavior: "smooth" });
    }
    if (e.target.closest("[data-del]")) { write(list.filter(x => x !== w)); render(); }
    if (e.target.closest("[data-rename]")) {
      const v = await dialog({ title: "Rename workflow", fields: [{ name: "name", value: w.name, required: true }], ok: "Save" });
      if (v?.name) { w.name = v.name.trim(); write(list); render(); }
    }
  });

  $("#wf-export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ format: "pdfnova-workflows-v1", exported: Date.now(), workflows: read() }, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "workflows.json" });
    a.click(); URL.revokeObjectURL(a.href);
  });
  $("#wf-import").addEventListener("click", () => $("#wf-import-input").click());
  $("#wf-import-input").addEventListener("change", async e => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      const incoming = (data.workflows || []).filter(w => w && w.name && Array.isArray(w.steps) && w.steps.every(s => s && typeof s.type === "string"));
      if (!incoming.length) throw new Error();
      const list = read(), ids = new Set(list.map(w => w.id));
      incoming.forEach(w => { if (ids.has(w.id)) w.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 5); list.push(w); });
      write(list); render(); toast(`Imported ${incoming.length} workflow${incoming.length > 1 ? "s" : ""}`);
    } catch { toast("That file doesn't contain workflows", "err"); }
  });

  // ---------- running ----------
  document.addEventListener("workflow-run", async () => {
    if (!current) return toast("Choose a workflow first", "err");
    const progress = $("#wf-progress"), btn = $("#submit-btn");
    let ids = Tool.readyFiles().map(f => f.id);
    btn.disabled = true;
    const line = (i, state, note = "") => {
      const el = progress.querySelector(`[data-step="${i}"]`);
      el.innerHTML = `${state === "run" ? `<span class="spinner" style="width:16px;height:16px;border-width:2px;margin:0"></span>` : icon(state === "ok" ? "check" : state === "err" ? "alert" : "clock")}
        <span style="flex:1">${i + 1}. ${esc(current.steps[i].title || current.steps[i].type)}</span><span class="muted small">${esc(note)}</span>`;
    };
    progress.innerHTML = current.steps.map((_, i) => `<div class="recent-item" data-step="${i}"></div>`).join("");
    current.steps.forEach((_, i) => line(i, "wait"));
    try {
      for (let i = 0; i < current.steps.length; i++) {
        line(i, "run");
        const { title, ...step } = current.steps[i];
        const body = { ...step, files: ids, workflowStep: i + 1 };
        const r = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (r.status === 402) throw new Error("Hourly task limit reached. Try again later.");
        if (!r.ok) throw new Error(await r.text());
        const taskId = await r.json();
        const t = await waitTask(taskId);
        if (t.status !== "Completed") throw new Error(t.failureReason || "Step failed");
        if (i === current.steps.length - 1) { line(i, "ok"); btn.disabled = false; Tool.showProcessing(taskId); return; }
        const next = await (await fetch(`/api/tasks/${taskId}/continue`, { method: "POST" })).json();
        ids = next.filter(f => /\.pdf$/i.test(f.name)).map(f => f.id);
        if (!ids.length) throw new Error("This step produced no PDF for the next step");
        line(i, "ok", (t.warnings || []).length ? "with warnings" : "");
      }
    } catch (err) {
      const i = [...progress.children].findIndex(el => el.querySelector(".spinner"));
      if (i >= 0) line(i, "err", err.message);
      toast(err.message, "err");
    }
    btn.disabled = false;
  });

  async function waitTask(id) {
    for (;;) {
      const r = await fetch(`/api/tasks/${id}/change?_=${Date.now()}`);
      if (r.status === 404) return { status: "Failed", failureReason: "Expired" };
      const t = await r.json();
      if (["completed", "failed"].includes(String(t.status).toLowerCase())) return t;
      await new Promise(res => setTimeout(res, 1500));
    }
  }

  render();
})();
