"""Generated-data browser checks for shared navigation/upload/workflow features."""
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
import pypdf
from qa.tool_scenarios import fixture


def main():
    base=(sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:18088").rstrip("/")
    out=ROOT/"data-qa-pool";out.mkdir(exist_ok=True)
    results=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();context=browser.new_context(viewport={"width":1365,"height":940},accept_downloads=True)
        page=context.new_page();page.set_default_timeout(15000)
        page.on("pageerror",lambda e:errors.append(str(e)))

        def check(name,fn):
            errors.clear()
            try: fn();assert not errors,errors;results.append({"name":name,"passed":True});print("PASS",name,flush=True)
            except Exception as e:
                results.append({"name":name,"passed":False,"error":str(e)})
                page.screenshot(path=str(out/("shared-"+str(len(results))+".png")))
                print("FAIL",name,str(e)[:300],flush=True)

        def home():
            page.goto(base)
            chips=page.locator("[data-cat]")
            for i in range(chips.count()):
                chip=chips.nth(i);chip.click()
                assert chip.get_attribute("aria-pressed")=="true"
                assert page.locator(".tool-card:visible").count()>0
            page.locator('[data-cat="all"]').click()
            page.locator("#tool-search").fill("not-a-tool-xyz")
            assert page.locator("#no-results").is_visible()
            page.locator("#tool-search").fill("sign")
            assert page.locator(".tool-card:visible").count()>0
            page.locator("#theme-btn").click();theme=page.locator("html").get_attribute("data-theme")
            page.reload();assert page.locator("html").get_attribute("data-theme")==theme
            page.locator("#theme-btn").click();assert page.locator("html").get_attribute("data-theme")!=theme
        check("all home categories, search and both theme transitions",home)

        def upload_errors():
            page.goto(base+"/merge-pdf")
            page.locator("#file-input").set_input_files({"name":"bad.exe","buffer":b"bad","mimeType":"application/octet-stream"})
            assert page.locator(".toast").filter(has_text="supported").count()>0
            assert page.evaluate("Tool.readyFiles().length")==0
            n,b,m=fixture("one")
            page.locator("#file-input").set_input_files([{"name":"first.pdf","buffer":b,"mimeType":m},{"name":"second.pdf","buffer":b,"mimeType":m}])
            page.wait_for_function("()=>Tool.readyFiles().length===2")
            page.locator("[data-remove]").first.click()
            assert page.evaluate("Tool.readyFiles().length")==1
            page.locator('#task-form [data-action="reset"]').click()
            assert page.locator("#stage-upload").is_visible()
            assert page.evaluate("Tool.readyFiles().length")==0
        check("unsupported upload, multiple upload, remove and reset",upload_errors)

        def url():
            page.goto(base+"/extract-pdf-pages")
            page.locator('[data-action="upload-menu"]').click()
            page.locator('[data-action="url"]').click()
            page.locator('.modal [name="url"]').fill("http://127.0.0.1/should-not-fetch.pdf")
            page.get_by_role("button",name="Add",exact=True).click()
            page.locator("#file-list").filter(has_text="private").wait_for()
            assert page.evaluate("Tool.readyFiles().length")==0
        check("URL dialog rejects private hosts without adding a file",url)

        def selection_validation():
            for slug in ("extract-pdf-pages","delete-pdf-pages"):
                page.goto(base+"/"+slug)
                n,b,m=fixture("pdf")
                page.locator("#file-input").set_input_files({"name":n,"buffer":b,"mimeType":m})
                page.wait_for_function("()=>Tool.readyFiles().length===1")
                page.locator("#submit-btn").click()
                page.locator(".toast").filter(has_text="Select at least one page").wait_for()
                assert page.locator("#task-form").is_visible()
                assert page.locator("#stage-result").is_hidden()
        check("extract/delete retain required-selection validation",selection_validation)

        def workflows():
            page.goto(base+"/workflows")
            payload={"workflows":[{"id":"pool","name":"Pool workflow","steps":[{"type":"extractPages","pages":"1-2"},{"type":"pageNumbers","pattern":"POOL WF [PAGE_ARABIC]"}]}]}
            blob=json.dumps(payload).encode()
            page.locator("#wf-import-input").set_input_files({"name":"pool.json","buffer":blob,"mimeType":"application/json"})
            page.get_by_role("button",name="Rename Pool workflow",exact=True).click()
            page.locator('.modal [name="name"]').fill("Renamed pool")
            page.get_by_role("button",name="Save",exact=True).click()
            with page.expect_download() as download: page.locator("#wf-export").click()
            exported=json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
            assert exported["workflows"][0]["name"]=="Renamed pool"
            page.get_by_role("button",name="Use workflow Renamed pool",exact=True).click()
            n,b,m=fixture("pdf")
            page.locator("#file-input").set_input_files({"name":n,"buffer":b,"mimeType":m})
            page.wait_for_function("()=>Tool.readyFiles().length===1")
            page.locator("#submit-btn").click()
            page.locator("#stage-result .state-icon.ok").wait_for(timeout=60000)
            response=context.request.get(page.locator("#stage-result a[download]").first.get_attribute("href"))
            assert response.ok
            doc=pypdf.PdfReader(io.BytesIO(response.body()));assert len(doc.pages)==2
            assert "POOL WF 2" in doc.pages[1].extract_text()
            page.goto(base+"/workflows")
            page.locator("#wf-import-input").set_input_files({"name":"again.json","buffer":blob,"mimeType":"application/json"})
            page.wait_for_function("()=>JSON.parse(localStorage.workflows).length===2")
            assert page.evaluate("new Set(JSON.parse(localStorage.workflows).map(w=>w.id)).size")==2
            page.once("dialog",lambda dialog:dialog.accept())
            page.get_by_role("button",name="Delete Renamed pool",exact=True).click()
            assert page.evaluate("JSON.parse(localStorage.workflows).length")==1
        check("workflow import, rename, export, real chain, duplicate IDs and delete",workflows)
        browser.close()
    (out/"shared-feature-results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(f"{sum(r['passed'] for r in results)}/{len(results)} shared feature groups passed",flush=True)
    return int(any(not r["passed"] for r in results))


if __name__=="__main__": raise SystemExit(main())
