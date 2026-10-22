/* Home page: client-side tool search and category chips. */
(() => {
  const q = document.getElementById("tool-search"), chips = document.querySelectorAll(".chip"), none = document.getElementById("no-results");
  if (!q) return;
  let cat = "all";
  function apply() {
    const term = q.value.trim().toLowerCase();
    let any = false;
    document.querySelectorAll(".tool-section").forEach(sec => {
      const key = sec.dataset.section;
      const sectionOn = term ? key !== "popular" : (cat === "all" || key === cat);
      let visible = 0;
      sec.querySelectorAll(".tool-card").forEach(card => {
        const on = sectionOn && (!term || card.dataset.search.includes(term));
        card.hidden = !on; if (on) visible++;
      });
      sec.hidden = visible === 0; if (visible) any = true;
    });
    none.hidden = any;
  }
  q.addEventListener("input", apply);
  q.addEventListener("keydown", e => { if (e.key === "Escape") { q.value = ""; apply(); } });
  chips.forEach(c => c.addEventListener("click", () => {
    chips.forEach(x => x.setAttribute("aria-pressed", String(x === c))); cat = c.dataset.cat; q.value = ""; apply();
  }));
  apply();
})();
