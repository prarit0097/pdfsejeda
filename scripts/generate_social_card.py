"""Render the original code-based social preview without external image/font APIs."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
SVG='''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<defs><linearGradient id="brand"><stop stop-color="#5b4dff"/><stop offset="1" stop-color="#9e4dc4"/></linearGradient></defs>
<rect width="1200" height="630" fill="#f7f7fc"/>
<rect x="62" y="68" width="100" height="100" rx="24" fill="url(#brand)"/>
<path d="M91 89h28l17 17v39H91z" fill="white"/><path d="M119 89v17h17" fill="#d8d5ff"/>
<text x="194" y="129" font-family="Arial,sans-serif" font-size="28" fill="#514e69">pdf.praritsidana.com</text>
<text x="62" y="280" font-family="Arial,sans-serif" font-size="76" font-weight="700" fill="#171720">Prarit Sidana PDF</text>
<text x="65" y="355" font-family="Arial,sans-serif" font-size="34" fill="#514e69">Edit. Sign. Merge. Compress. Convert.</text>
<rect x="65" y="427" width="548" height="72" rx="16" fill="url(#brand)"/>
<text x="91" y="474" font-family="Arial,sans-serif" font-size="30" font-weight="700" fill="white">43 PDF tools. No sign-up.</text>
<path d="M790 540c150-220 290-260 410-130v220H720z" fill="#ece9ff"/>
</svg>'''


if __name__=="__main__":
    folder=ROOT/"app/static/img"
    (folder/"social-card.svg").write_text(SVG,encoding="utf-8")
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={"width":1200,"height":630},device_scale_factor=1)
        page.set_content('<html><body style="margin:0">'+SVG+'</body></html>')
        page.screenshot(path=str(folder/"social-card.png"))
        browser.close()
    print("Generated original 1200x630 social-card.png")
