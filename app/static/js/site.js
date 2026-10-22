/* Site-wide helpers: theme, "All tools" menu, toasts, small modal dialogs. Exposed as window.UI. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);

  // theme
  const themeBtn = $("#theme-btn");
  function currentTheme() {
    return document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function paintThemeIcon() {
    if (!themeBtn) return;
    const dark = currentTheme() === "dark";
    themeBtn.innerHTML = icon(dark ? "sun" : "moon");
    themeBtn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    themeBtn.title = dark ? "Switch to light theme" : "Switch to dark theme";
  }
  themeBtn?.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    paintThemeIcon();
  });

  // mega menu
  const megaBtn = $("#all-tools-btn"), mega = $("#mega");
  megaBtn?.addEventListener("click", e => {
    e.stopPropagation();
    const open = mega.hidden;
    mega.hidden = !open; megaBtn.setAttribute("aria-expanded", open);
  });
  document.addEventListener("click", e => {
    if (mega && !mega.hidden && !mega.contains(e.target)) { mega.hidden = true; megaBtn.setAttribute("aria-expanded", "false"); }
  });
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !mega || mega.hidden) return;
    mega.hidden = true; megaBtn.setAttribute("aria-expanded", "false");
    if (mega.contains(document.activeElement)) megaBtn.focus();
  });

  // range inputs show their value in the next <output> (no inline handlers: CSP has no 'unsafe-inline' scripts)
  document.addEventListener("input", e => {
    const r = e.target.closest?.("input[type=range][data-range-output]");
    if (r && r.nextElementSibling) r.nextElementSibling.textContent = r.value;
  });

  function icon(name, cls = "") {
    return `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  }

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = "toast " + kind; el.textContent = msg;
    if (kind === "err") el.setAttribute("role", "alert");
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** prompt-like modal. fields: [{name,label,type,placeholder,value}] -> Promise<object|null> */
  let dialogSeq = 0;
  function dialog({ title, text = "", fields = [], ok = "OK", cancel = "Cancel" }) {
    return new Promise(resolve => {
      const id = "dlg" + (++dialogSeq), opener = document.activeElement;
      const back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = `<form class="modal" role="dialog" aria-modal="true" aria-labelledby="${id}-t" ${text ? `aria-describedby="${id}-d"` : ""} novalidate>
        <h3 id="${id}-t">${esc(title)}</h3>${text ? `<p class="muted" id="${id}-d">${esc(text)}</p>` : ""}
        ${fields.map(f => `<label class="opt" style="display:block;margin-top:12px"><span class="lbl">${esc(f.label || f.placeholder || f.name)}</span>
          <input class="input" name="${esc(f.name)}" type="${esc(f.type || "text")}" placeholder="${esc(f.placeholder || "")}" value="${esc(f.value || "")}" ${f.required ? "required" : ""} ${f.type === "password" ? 'autocomplete="off"' : ""}></label>
          <div class="field-err small" hidden role="alert"></div>`).join("")}
        <div class="row">${cancel ? `<button type="button" class="btn btn-ghost" data-x>${esc(cancel)}</button>` : ""}<button class="btn btn-primary">${esc(ok)}</button></div></form>`;
      document.body.appendChild(back);
      document.body.classList.add("modal-open");
      const form = back.querySelector("form");
      const first = form.querySelector("input"); (first || form.querySelector(".btn-primary")).focus();
      const close = v => {
        back.remove(); document.body.classList.toggle("modal-open", !!document.querySelector(".modal-back"));
        if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
        resolve(v);
      };
      form.addEventListener("submit", e => {
        e.preventDefault();
        // validate here (native bubbles are hidden behind novalidate so the messages match the site's style)
        let bad = null;
        form.querySelectorAll("input").forEach(inp => {
          const msgEl = inp.closest("label").nextElementSibling;
          let msg = "";
          if (inp.required && !inp.value.trim()) msg = "This field is required";
          else if (inp.type === "url" && inp.value.trim() && !/^(https?:\/\/)?[^\s/$.?#]+\.[^\s]+$/i.test(inp.value.trim())) msg = "Enter a web address like https://example.com/file.pdf";
          msgEl.textContent = msg; msgEl.hidden = !msg; inp.setAttribute("aria-invalid", msg ? "true" : "false");
          if (msg && !bad) bad = inp;
        });
        if (bad) return bad.focus();
        close(Object.fromEntries(new FormData(form)));
      });
      back.querySelector("[data-x]")?.addEventListener("click", () => close(null));
      back.addEventListener("keydown", e => {
        if (e.key === "Escape") { e.stopPropagation(); close(null); }
        if (e.key === "Tab") { // keep focus inside the dialog
          const els = [...form.querySelectorAll("input, button")].filter(x => !x.disabled);
          const i = els.indexOf(document.activeElement);
          if (e.shiftKey && i <= 0) { e.preventDefault(); els[els.length - 1].focus(); }
          else if (!e.shiftKey && i === els.length - 1) { e.preventDefault(); els[0].focus(); }
        }
      });
      back.addEventListener("mousedown", e => { if (e.target === back) close(null); });
    });
  }

  function fmtSize(n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function compressRanges(nums) {
    const p = [...new Set(nums)].sort((a, b) => a - b), out = [];
    for (let i = 0; i < p.length; i++) {
      let j = i;
      while (j + 1 < p.length && p[j + 1] === p[j] + 1) j++;
      out.push(i === j ? `${p[i]}` : `${p[i]}-${p[j]}`);
      i = j;
    }
    return out.join(",");
  }

  window.UI = { icon, toast, dialog, fmtSize, esc, compressRanges, $ };
  paintThemeIcon();
})();
