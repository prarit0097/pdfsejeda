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
    if (themeBtn) themeBtn.innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon");
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
  document.addEventListener("keydown", e => { if (e.key === "Escape" && mega) mega.hidden = true; });

  function icon(name, cls = "") {
    return `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  }

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = "toast " + kind; el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** prompt-like modal. fields: [{name,label,type,placeholder,value}] -> Promise<object|null> */
  function dialog({ title, text = "", fields = [], ok = "OK", cancel = "Cancel" }) {
    return new Promise(resolve => {
      const back = document.createElement("div");
      back.className = "modal-back";
      back.innerHTML = `<form class="modal" role="dialog" aria-modal="true">
        <h3>${esc(title)}</h3>${text ? `<p class="muted">${esc(text)}</p>` : ""}
        ${fields.map(f => `<label class="opt" style="display:block;margin-top:12px"><span class="lbl">${esc(f.label || "")}</span>
          <input class="input" name="${f.name}" type="${f.type || "text"}" placeholder="${esc(f.placeholder || "")}" value="${esc(f.value || "")}" ${f.required ? "required" : ""}></label>`).join("")}
        <div class="row">${cancel ? `<button type="button" class="btn btn-ghost" data-x>${esc(cancel)}</button>` : ""}<button class="btn btn-primary">${esc(ok)}</button></div></form>`;
      document.body.appendChild(back);
      const form = back.querySelector("form");
      const first = form.querySelector("input"); (first || form.querySelector(".btn-primary")).focus();
      const close = v => { back.remove(); resolve(v); };
      form.addEventListener("submit", e => { e.preventDefault(); close(Object.fromEntries(new FormData(form))); });
      back.querySelector("[data-x]")?.addEventListener("click", () => close(null));
      back.addEventListener("keydown", e => { if (e.key === "Escape") close(null); });
      back.addEventListener("click", e => { if (e.target === back) close(null); });
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
