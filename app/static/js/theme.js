/* Applies the saved theme before first paint (loaded synchronously in <head>). */
try { var t = localStorage.getItem("theme"); if (t === "dark" || t === "light") document.documentElement.dataset.theme = t; } catch (e) {}
