"""Read-only sitemap crawl and responsive branding checks; safe on production."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import httpx
from playwright.sync_api import sync_playwright
from qa.seo_html import Head


def main():
    base=(sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:18088").rstrip("/")
    results=[]
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        r=client.get(base+"/sitemap.xml");r.raise_for_status()
        root=ET.fromstring(r.content)
        urls=[n.text for n in root.findall("{*}url/{*}loc")]
        assert len(urls)==56==len(set(urls))
        titles=set();descriptions=set()
        for url in urls:
            path=urlsplit(url).path
            r=client.get(base+path);assert r.status_code==200,(path,r.status_code)
            h=Head(r.text)
            assert h.canonical==[url] and h.meta["og:url"]==url
            assert h.title==h.meta["og:title"] and h.h1==1
            assert "index, follow" in h.meta["robots"]
            assert h.title not in titles and h.meta["description"] not in descriptions
            titles.add(h.title);descriptions.add(h.meta["description"])
            assert json.loads(h.jsonld[0])["@context"]=="https://schema.org"
            results.append({"path":path,"passed":True})
        assert "Sitemap:" in client.get(base+"/robots.txt").text
        assert "noindex" in client.get(base+"/api/tools").headers["x-robots-tag"]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for width in (375,1365):
            page=browser.new_page(viewport={"width":width,"height":900});errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            for path in ("/","/pdf-editor","/guides",urlsplit(urls[-1]).path):
                page.goto(base+path);page.wait_for_load_state("domcontentloaded")
                logo=page.locator(".site-header .logo")
                assert logo.get_attribute("aria-label")=="Prarit Sidana PDF home"
                assert logo.locator(".brand-short" if width==375 else ".brand-full").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"),(width,path)
                assert not errors,errors
                results.append({"path":path,"viewport":width,"passed":True})
            page.close()
        browser.close()
    out=ROOT/"data-qa-seo";out.mkdir(exist_ok=True)
    report={"base_url":base,"public_pages":len(urls),"responsive_checks":8,"checks":results,"status":"passed"}
    (out/"crawl-results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="checks"}))
    return 0


if __name__=="__main__":raise SystemExit(main())
