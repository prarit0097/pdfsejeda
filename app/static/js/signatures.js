/* Local visual signatures: device library, type/draw/image/camera creation. */
(() => {
  const { toast } = window.UI;
  const FONTS = ["Dancing Script", "Caveat", "Homemade Apple", "Sacramento", "Allura", "Great Vibes", "Pacifico", "Satisfy", "Shadows Into Light", "Marck Script", "Parisienne", "Yellowtail"];
  const COLORS = ["#506aef", "#2c4c9e", "#3925ed", "#0000ff", "#555555", "#333333", "#000000"];
  let cancelActive = null;
  const png = s => typeof s === "string" && s.length < 1500000 && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(s);
  function library() {
    try { const items = JSON.parse(localStorage.getItem("signatures") || "[]"); return Array.isArray(items) ? items.filter(png).slice(0, 8) : []; } catch { return []; }
  }
  function store(items) {
    try { while (JSON.stringify(items).length > 2500000) items.pop(); localStorage.setItem("signatures", JSON.stringify(items.slice(0, 8))); }
    catch { toast("Your browser could not save the signature on this device."); }
  }
  const image = src => new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error("Could not read this image.")); img.src = src; });
  async function result(src) { const img = await image(src); return { dataUrl: src, ratio: img.width / img.height }; }
  function trim(canvas) {
    const { width: w, height: h } = canvas, data = canvas.getContext("2d").getImageData(0, 0, w, h).data;
    let l = w, t = h, r = -1, b = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (data[(y * w + x) * 4 + 3] > 12) { l = Math.min(l, x); r = Math.max(r, x); t = Math.min(t, y); b = Math.max(b, y); }
    if (r < l) return null;
    const out = document.createElement("canvas"); out.width = r - l + 13; out.height = b - t + 13;
    out.getContext("2d").drawImage(canvas, l, t, r - l + 1, b - t + 1, 6, 6, r - l + 1, b - t + 1);
    return { dataUrl: out.toDataURL("image/png"), ratio: out.width / out.height };
  }
  async function variants(src) {
    const img = await image(src), k = Math.min(1, 1000 / Math.max(img.width, img.height));
    const original = document.createElement("canvas"); original.width = Math.max(1, Math.round(img.width * k)); original.height = Math.max(1, Math.round(img.height * k));
    original.getContext("2d").drawImage(img, 0, 0, original.width, original.height);
    const outputs = [{ dataUrl: original.toDataURL("image/png"), ratio: original.width / original.height }];
    for (const mode of [0, 1]) {
      const c = document.createElement("canvas"); c.width = original.width; c.height = original.height;
      const ctx = c.getContext("2d"); ctx.drawImage(original, 0, 0);
      const data = ctx.getImageData(0, 0, c.width, c.height);
      for (let i = 0; i < data.data.length; i += 4) {
        const rgb = [data.data[i], data.data[i + 1], data.data[i + 2]], mean = (rgb[0] + rgb[1] + rgb[2]) / 3;
        const neutral = Math.max(...rgb) - Math.min(...rgb) < 48;
        // A removes light paper; B also removes neutral grey paper/shadows.
        const alpha = mode === 0 ? Math.min(1, Math.max(0, (244 - mean) / 38)) : neutral ? Math.min(1, Math.max(0, (150 - mean) / 65)) : Math.min(1, Math.max(0, (245 - mean) / 25));
        data.data[i + 3] *= alpha;
      }
      ctx.putImageData(data, 0, 0); outputs.push(trim(c));
    }
    return outputs;
  }

  function choose(anchor) {
    cancelActive?.();
    return new Promise(resolve => {
      const menu = document.createElement("div"); menu.className = "signature-menu"; menu.setAttribute("aria-label", "Saved signatures");
      let saved = library();
      function render() {
        menu.replaceChildren();
        for (const [i, src] of saved.entries()) {
          const row = document.createElement("div"); row.className = "signature-menu-row";
          const use = document.createElement("button"); use.type = "button"; use.className = "signature-reuse"; use.setAttribute("aria-label", `Use saved signature ${i + 1}`);
          const img = document.createElement("img"); img.src = src; img.alt = "Saved signature"; use.append(img);
          use.onclick = async () => { try { finish(await result(src)); } catch { toast("This saved signature could not be loaded."); } };
          const remove = document.createElement("button"); remove.type = "button"; remove.className = "signature-remove"; remove.textContent = "×"; remove.setAttribute("aria-label", `Remove saved signature ${i + 1}`);
          remove.onclick = () => { saved.splice(i, 1); store(saved); render(); menu.querySelector("button")?.focus(); };
          row.append(use, remove); menu.append(row);
        }
        const add = document.createElement("button"); add.type = "button"; add.className = "btn signature-new"; add.textContent = "+ New Signature";
        add.onclick = () => { cleanup(); create(anchor).then(resolve); }; menu.append(add);
      }
      function cleanup() { menu.remove(); document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", key); window.removeEventListener("resize", position); document.removeEventListener("scroll", position, true); anchor.setAttribute("aria-expanded", "false"); cancelActive = null; }
      function finish(value) { cleanup(); anchor.focus({ preventScroll: true }); resolve(value); }
      function outside(e) { if (!menu.contains(e.target) && !anchor.contains(e.target)) finish(null); }
      function key(e) { if (e.key === "Escape") { e.preventDefault(); finish(null); } }
      function position() { const r = anchor.getBoundingClientRect(); menu.style.left = Math.max(8, Math.min(innerWidth - menu.offsetWidth - 8, r.left)) + "px"; menu.style.top = Math.max(8, Math.min(innerHeight - menu.offsetHeight - 8, r.bottom + 4)) + "px"; }
      render(); document.body.append(menu); anchor.setAttribute("aria-expanded", "true"); position();
      document.addEventListener("pointerdown", outside); document.addEventListener("keydown", key); window.addEventListener("resize", position); document.addEventListener("scroll", position, true);
      cancelActive = () => finish(null); menu.querySelector("button").focus();
    });
  }

  function create(anchor) {
    cancelActive?.();
    return new Promise(resolve => {
      const back = document.createElement("div"); back.className = "modal-back signature-back";
      back.innerHTML = `<div class="signature-modal" role="dialog" aria-modal="true" aria-labelledby="signature-title">
        <header><h2 id="signature-title">Create signature</h2><button type="button" data-close aria-label="Close signature dialog">×</button></header>
        <div class="signature-tabs"><div role="tablist" aria-label="Signature method">${[["type", "Type"], ["draw", "Draw"], ["upload", "Upload Image"], ["camera", "Camera"]].map(([key, text]) => `<button type="button" role="tab" id="sig-tab-${key}" aria-controls="sig-pane-${key}" data-tab="${key}" aria-selected="${key === "type"}">${text}</button>`).join("")}</div><label class="check"><input type="checkbox" data-remember checked> Save signature</label></div>
        <div class="signature-content">
          <section role="tabpanel" id="sig-pane-type" aria-labelledby="sig-tab-type" data-pane="type"><input class="input sig-type" aria-label="Your name" placeholder="Your name" maxlength="200" autocomplete="name"><div class="signature-colors" aria-label="Signature colour"></div><div class="sig-fonts">${FONTS.map((font, i) => `<button type="button" data-font="${font}" aria-label="${font}" aria-pressed="${i === 0}" style="font-family:'${font}'">Your signature</button>`).join("")}</div></section>
          <section role="tabpanel" id="sig-pane-draw" aria-labelledby="sig-tab-draw" data-pane="draw" hidden><div class="signature-colors" aria-label="Pen colour"></div><canvas class="sig-pad" width="1200" height="420" aria-label="Draw your signature"></canvas><div class="signature-draw-actions"><span>Draw with your mouse, finger or pen.</span><label>Pen width <input type="range" min="1" max="10" value="3" data-pen-width></label><button type="button" class="btn" data-clear>Clear</button></div></section>
          <section role="tabpanel" id="sig-pane-upload" aria-labelledby="sig-tab-upload" data-pane="upload" hidden><button type="button" class="btn" data-file-pick="signature-image-file">Choose signature image</button><input type="file" id="signature-image-file" accept="image/*" hidden><p>Upload a photo or scan of your signature.</p><div class="signature-versions" data-versions="upload"></div></section>
          <section role="tabpanel" id="sig-pane-camera" aria-labelledby="sig-tab-camera" data-pane="camera" hidden><p>Photograph a signature on paper, then choose an image version.</p><div class="signature-camera-actions"><button type="button" class="btn" data-camera-start>Start camera</button><button type="button" class="btn" data-camera-capture disabled>Take photo</button><button type="button" class="btn" data-file-pick="signature-camera-file">Choose / take a photo</button><input type="file" id="signature-camera-file" accept="image/*" capture="environment" hidden></div><video class="signature-video" autoplay muted playsinline hidden></video><p data-camera-status role="status"></p><div class="signature-versions" data-versions="camera"></div></section>
          <p class="signature-error" role="alert" hidden></p>
        </div><footer><p>Saved signatures stay in this browser. Uncheck Save signature to use it once.</p><button type="button" class="btn btn-editor" data-ok>Save</button></footer></div>`;
      document.body.append(back); document.body.classList.add("modal-open");
      const modal = back.firstElementChild, pad = back.querySelector(".sig-pad"), ctx = pad.getContext("2d"), input = back.querySelector(".sig-type"), video = back.querySelector("video");
      let tab = "type", font = FONTS[0], color = "#000000", inked = false, drawing = false, stream = null, closed = false, busy = false, generation = 0;
      const chosen = { upload: null, camera: null };
      function error(message) { const el = back.querySelector(".signature-error"); el.textContent = message; el.hidden = !message; }
      function stopCamera() { stream?.getTracks().forEach(t => t.stop()); stream = null; video.srcObject = null; video.hidden = true; back.querySelector("[data-camera-capture]").disabled = true; }
      function close(value) { if (closed) return; closed = true; generation++; stopCamera(); back.remove(); document.body.classList.remove("modal-open"); document.removeEventListener("keydown", key); cancelActive = null; anchor?.focus({ preventScroll: true }); resolve(value); }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(null); }
        if (e.key === "Tab") {
          const items = [...modal.querySelectorAll('button,input,video,[tabindex]')].filter(el => !el.disabled && el.getClientRects().length);
          const first = items[0], last = items.at(-1);
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
      document.addEventListener("keydown", key); cancelActive = () => close(null);
      function selectTab(next) {
        if (next !== "camera") stopCamera(); tab = next; error("");
        back.querySelectorAll("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
        back.querySelectorAll("[data-pane]").forEach(p => { p.hidden = p.dataset.pane !== tab; });
        if (tab === "type") input.focus();
      }
      function preview() { back.querySelectorAll("[data-font]").forEach(b => { b.textContent = input.value.trim() || "Your signature"; b.style.color = color; b.setAttribute("aria-pressed", String(b.dataset.font === font)); }); }
      function colors() {
        back.querySelectorAll(".signature-colors").forEach(row => {
          row.replaceChildren(); for (const value of COLORS) { const b = document.createElement("button"); b.type = "button"; b.dataset.color = value; b.setAttribute("aria-label", "Colour " + value); b.setAttribute("aria-pressed", String(value === color)); b.style.background = value; row.append(b); }
        });
      }
      colors(); input.addEventListener("input", () => { error(""); preview(); });
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      const position = e => { const r = pad.getBoundingClientRect(); return [(e.clientX - r.left) * pad.width / r.width, (e.clientY - r.top) * pad.height / r.height]; };
      pad.addEventListener("pointerdown", e => { if (e.button !== 0) return; e.preventDefault(); error(""); drawing = true; inked = true; pad.setPointerCapture(e.pointerId); ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = Number(back.querySelector("[data-pen-width]").value) * pad.width / pad.clientWidth; const [x, y] = position(e); ctx.beginPath(); ctx.arc(x, y, ctx.lineWidth / 2, 0, Math.PI * 2); ctx.fill(); ctx.beginPath(); ctx.moveTo(x, y); });
      pad.addEventListener("pointermove", e => { if (drawing) { ctx.lineTo(...position(e)); ctx.stroke(); } });
      for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) pad.addEventListener(name, () => { drawing = false; });
      async function prepare(src, target) {
        const token = ++generation; error(""); chosen[target] = null;
        const container = back.querySelector(`[data-versions="${target}"]`); container.textContent = "Preparing image versions…";
        try {
          const options = await variants(src); if (closed || token !== generation) return;
          container.innerHTML = '<h3>Choose an image version:</h3>';
          for (const [i, label] of ["Original", "Transparent A", "Transparent B"].entries()) {
            const button = document.createElement("button"); button.type = "button"; button.dataset.variant = String(i); button.setAttribute("aria-label", label); button.setAttribute("aria-pressed", "false"); button.disabled = !options[i];
            const img = document.createElement("img"); img.alt = label; if (options[i]) img.src = options[i].dataUrl;
            const text = document.createElement("span"); text.textContent = label; button.append(img, text);
            button.onclick = () => { error(""); chosen[target] = options[i]; container.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b === button))); };
            container.append(button);
          }
          container.querySelector('[data-variant="1"]:not(:disabled)')?.click();
        } catch { container.textContent = ""; if (!closed) error("Could not read this image. Choose a PNG, JPEG, GIF or WebP image."); }
      }
      for (const [selector, target] of [["#signature-image-file", "upload"], ["#signature-camera-file", "camera"]]) back.querySelector(selector).addEventListener("change", async e => {
        const file = e.target.files[0]; e.target.value = ""; if (!file) return;
        if (file.size > 20 * 1024 * 1024) return error("Choose an image smaller than 20 MB.");
        stopCamera(); const url = URL.createObjectURL(file); try { await prepare(url, target); } finally { URL.revokeObjectURL(url); }
      });
      back.addEventListener("click", async e => {
        const b = e.target.closest("button"); if (e.target === back || b?.hasAttribute("data-close")) return close(null);
        if (!b) return;
        if (b.dataset.filePick) back.querySelector("#" + b.dataset.filePick).click();
        if (b.dataset.tab) selectTab(b.dataset.tab);
        if (b.dataset.font) { font = b.dataset.font; preview(); }
        if (b.dataset.color) { color = b.dataset.color; colors(); preview(); if (inked) { ctx.globalCompositeOperation = "source-in"; ctx.fillStyle = color; ctx.fillRect(0, 0, pad.width, pad.height); ctx.globalCompositeOperation = "source-over"; } }
        if (b.hasAttribute("data-clear")) { error(""); ctx.clearRect(0, 0, pad.width, pad.height); inked = false; }
        if (b.hasAttribute("data-camera-start")) {
          stopCamera(); const status = back.querySelector("[data-camera-status]");
          if (!navigator.mediaDevices?.getUserMedia) { status.textContent = "Camera is unavailable here. Use Choose / take a photo instead."; return; }
          b.disabled = true; status.textContent = "Waiting for camera permission…";
          try {
            const next = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
            if (closed || tab !== "camera") { next.getTracks().forEach(t => t.stop()); return; }
            stream = next; video.srcObject = next; video.hidden = false; await video.play();
            if (!closed && tab === "camera") { status.textContent = "Position your signature, then take a photo."; back.querySelector("[data-camera-capture]").disabled = false; }
          } catch { stopCamera(); status.textContent = "Camera access was not available. Allow camera access in your browser, or choose a photo."; }
          finally { b.disabled = false; }
        }
        if (b.hasAttribute("data-camera-capture")) {
          if (!video.videoWidth) return error("Wait until the camera preview is ready.");
          const c = document.createElement("canvas"); c.width = video.videoWidth; c.height = video.videoHeight; c.getContext("2d").drawImage(video, 0, 0); stopCamera(); await prepare(c.toDataURL("image/png"), "camera");
        }
        if (b.hasAttribute("data-ok") && !busy) {
          busy = true; b.disabled = true; error("");
          try {
            let out;
            if (tab === "type") {
              const name = input.value.trim(); if (!name) throw new Error("Type your name first.");
              await document.fonts.load(`100px '${font}'`);
              const c = document.createElement("canvas"), ctx = c.getContext("2d"); ctx.font = `100px '${font}'`;
              const width = ctx.measureText(name).width, scale = Math.min(1, 1950 / Math.max(1, width)); c.width = Math.min(2048, Math.ceil(width * scale + 80)); c.height = 260;
              ctx.font = `${100 * scale}px '${font}'`; ctx.fillStyle = color; ctx.textBaseline = "middle"; ctx.fillText(name, 35, 130); out = trim(c);
            } else if (tab === "draw") out = inked ? trim(pad) : null;
            else out = chosen[tab];
            if (!out) throw new Error(tab === "draw" ? "Draw your signature first." : "Choose an image version first.");
            if (!png(out.dataUrl)) throw new Error("This signature image is too large. Choose a simpler or smaller image.");
            if (closed) return;
            if (back.querySelector("[data-remember]").checked) store([out.dataUrl, ...library().filter(s => s !== out.dataUrl)]);
            close(out);
          } catch (e) { if (!closed) error(e.message || "Could not create this signature."); }
          finally { busy = false; b.disabled = false; }
        }
      });
      input.focus();
    });
  }
  window.PDFNovaSignatures = { choose };
})();
