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

  const valid = w => w && typeof w === "object" && typeof w.name === "string" && w.name.trim() && Array.isArray(w.steps) && w.steps.length &&
    w.steps.length <= 20 && w.steps.every(s => s && typeof s === "object" && typeof s.type === "string" && /^[A-Za-z]{2,40}$/.test(s.type));
  const sanitize = w => ({ ...w, steps: w.steps.map(Tool.cleanWorkflowStep).filter(Boolean) });
  const read = () => { try { const l = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(l) ? l.filter(valid).map(sanitize) : []; } catch { return []; } };
  const write = list => { try { localStorage.setItem(KEY, JSON.stringify(list.map(sanitize))); return true; } catch { toast("Browser storage is unavailable or full", "err"); return false; } };
  // Scrub secrets from workflows saved with earlier versions, including exports.
  try { const old = localStorage.getItem(KEY); if (old) localStorage.setItem(KEY, JSON.stringify(read())); } catch {}

  function render() {
    const list = read();
    const all = list.length ? list : [EXAMPLE];
    $("#wf-list").innerHTML = all.map(w => `
      <div class="recent-item" data-id="${esc(w.id)}">
        <span class="tool-ico" style="--c:var(--cat-pages);width:38px;height:38px">${icon("workflow")}</span>
        <div style="flex:1;min-width:0"><div style="font-weight:600">${esc(w.name)}</div>
          <div class="muted small">${w.steps.map(s => esc(s.title || s.type)).join(" → ")}</div></div>
        <button class="btn btn-sm btn-primary" type="button" data-run aria-label="Use workflow ${esc(w.name)}">Use</button>
        ${w.example ? "" : `<button class="icon-btn" type="button" data-rename title="Rename" aria-label="Rename ${esc(w.name)}">${icon("edit")}</button><button class="icon-btn" type="button" data-del title="Delete" aria-label="Delete ${esc(w.name)}">${icon("trash")}</button>`}
      </div>`).join("") + (list.length ? "" : `<p class="muted small" style="padding:0 18px 14px">You have no saved workflows yet, so here is an example.</p>`);
  }

  $("#wf-list").addEventListener("click", async e => {
    const row = e.target.closest("[data-id]"); if (!row) return;
    const list = read(), w = list.find(x => String(x.id) === row.dataset.id) || (row.dataset.id === "example" ? EXAMPLE : null);
    if (!w) return;
    if (e.target.closest("[data-run]")) {
      current = w;
      $("#wf-run").hidden = false;
      $("#wf-run-title").innerHTML = `<b>${esc(w.name)}</b>: ${w.steps.map(s => esc(s.title || s.type)).join(" → ")}`;
      $("#wf-run").scrollIntoView({ behavior: "smooth" });
    }
    if (e.target.closest("[data-del]")) {
      if (!confirm(`Delete the workflow "${w.name}"?`)) return;
      write(list.filter(x => x !== w)); render();
      if (current?.id === w.id) { current = null; $("#wf-run").hidden = true; }
    }
    if (e.target.closest("[data-rename]")) {
      const v = await dialog({ title: "Rename workflow", fields: [{ name: "name", label: "Name", value: w.name, required: true }], ok: "Save" });
      if (v?.name) { w.name = v.name.trim(); if (write(list)) { if (current?.id === w.id) current = w; render(); } }
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
      const incoming = (Array.isArray(data?.workflows) ? data.workflows : []).filter(valid).slice(0, 100);
      if (!incoming.length) throw new Error();
      const list = read(), ids = new Set(list.map(w => String(w.id)));
      incoming.forEach(w => {
        // keep only plain data: name, steps (each a flat task body); fresh ids so nothing collides
        let id = String(w.id ?? "");
        if (!/^[\w-]{1,40}$/.test(id) || ids.has(id) || id === "example") id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        ids.add(id);
        list.push({ id, name: String(w.name).trim().slice(0, 200), created: Number(w.created) || Date.now(), steps: w.steps.map(Tool.cleanWorkflowStep).filter(Boolean) });
      });
      if (write(list)) { render(); toast(`Imported ${incoming.length} workflow${incoming.length > 1 ? "s" : ""}`); }
    } catch { toast("That file doesn't contain workflows", "err"); }
  });

  // ---------- running ----------
  document.addEventListener("workflow-run", async () => {
    if (!current) return toast("Choose a workflow first", "err");
    const workflow = current; // selection cannot alter an in-flight chain
    const progress = $("#wf-progress"), btn = $("#submit-btn");
    let ids = Tool.readyFiles().map(f => f.id);
    if (!ids.length) return toast("Please add a file first", "err");
    btn.disabled = true;
    const line = (i, state, note = "") => {
      const el = progress.querySelector(`[data-step="${i}"]`);
      el.innerHTML = `${state === "run" ? `<span class="spinner" style="width:16px;height:16px;border-width:2px;margin:0"></span>` : icon(state === "ok" ? "check" : state === "err" ? "alert" : "clock")}
        <span style="flex:1">${i + 1}. ${esc(workflow.steps[i].title || workflow.steps[i].type)}</span><span class="muted small">${esc(note)}</span>`;
    };
    progress.innerHTML = workflow.steps.map((_, i) => `<div class="recent-item" data-step="${i}"></div>`).join("");
    workflow.steps.forEach((_, i) => line(i, "wait"));
    try {
      for (let i = 0; i < workflow.steps.length; i++) {
        line(i, "run");
        const { title, ...step } = workflow.steps[i];
        const body = { ...Tool.cleanWorkflowStep(step), files: ids, workflowStep: i + 1 };
        if (step.type === "encrypt") {
          const credentials = await dialog({ title: "Encryption password", text: "Enter passwords for this run. They are never saved in the workflow.", fields: [
            { name: "userPassword", label: "Open password", type: "password", required: true },
            ...(step.restrictPermissions ? [{ name: "ownerPassword", label: "Owner password", type: "password", required: true }] : []),
          ], ok: "Continue" });
          if (!credentials) throw new Error("Workflow cancelled");
          Object.assign(body, credentials);
        }
        const r = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (r.status === 402) throw new Error("Hourly task limit reached. Try again later.");
        if (!r.ok) throw new Error((Tool.errText ? Tool.errText(await r.text()) : await r.text()) || "The server rejected this step");
        const taskId = await r.json();
        const t = await waitTask(taskId);
        if (String(t.status).toLowerCase() !== "completed") throw new Error(t.failureReason || "Step failed");
        if (i === workflow.steps.length - 1) { line(i, "ok"); btn.disabled = false; Tool.showProcessing(taskId); return; }
        const cr = await fetch(`/api/tasks/${taskId}/continue`, { method: "POST" });
        if (!cr.ok) throw new Error(Tool.errText ? Tool.errText(await cr.text()) : "These files have expired");
        const next = await cr.json();
        ids = next.filter(f => /\.pdf$/i.test(f.name)).map(f => f.id);
        if (!ids.length) throw new Error("This step produced no PDF for the next step");
        if (step.type === "encrypt" && body.userPassword) {
          for (const id of ids) {
            const unlock = await fetch(`/api/files/${id}/password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: body.userPassword }) });
            if (!unlock.ok) throw new Error("Could not unlock this step's PDF for the next step");
          }
        }
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
      if (!r.ok) { await new Promise(res => setTimeout(res, 3000)); continue; }
      const t = await r.json();
      if (["completed", "failed"].includes(String(t.status).toLowerCase())) return t;
      await new Promise(res => setTimeout(res, 1500));
    }
  }

  render();
})();
