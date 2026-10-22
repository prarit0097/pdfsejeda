"""Submit every canonical tool through visible Chromium UI, with parsed outputs.

Run against an isolated local server, never public production (43+ tasks).
python scripts/tool_ui_regression.py http://127.0.0.1:18088
"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from playwright.sync_api import sync_playwright
from app.tools.registry import all_tools
from qa.tool_scenarios import SCENARIOS, scenario_files, validate_output

OUT=ROOT/"data-qa-pool"
BASE=(sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:18088").rstrip("/")


def run():
    OUT.mkdir(exist_ok=True)
    results=[]; exercised=set(); errors=[]
    mobile=os.environ.get("POOL_UI_MOBILE")=="1"
    tools={t.type:t for t in all_tools()}
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={"width":390,"height":844} if mobile else {"width":1365,"height":940},has_touch=mobile)
        page=context.new_page(); page.set_default_timeout(12000)
        page.on("pageerror",lambda e:errors.append(str(e)))

        def field(name): return page.locator('[name='+json.dumps(name)+']')

        def set_field(name,value):
            f=field(name)
            assert f.count(), ("Missing field",name)
            tag=f.first.evaluate("e=>e.tagName.toLowerCase()")
            kind=f.first.get_attribute("type")
            if kind=="radio":
                radio=f.locator('xpath=self::*[@value='+json.dumps(str(value))+']')
                radio.locator("..").click()
                assert radio.is_checked()
            elif kind=="checkbox": f.set_checked(bool(value))
            elif tag=="select": f.select_option(str(value))
            elif kind in ("range","color"):
                f.evaluate("(e,v)=>{e.value=String(v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}",value)
            else: f.fill(str(value))

        def options(tool):
            more=page.locator('[data-action="more"]')
            if more.count() and more.get_attribute("aria-expanded")=="false": more.click()
            byname={o.name:o for o in tool.options}
            def activate(o):
                for parent,wanted in (o.show_if or {}).items():
                    if parent in byname: activate(byname[parent])
                    set_field(parent,wanted[0] if isinstance(wanted,list) else wanted)
            for o in tool.options:
                activate(o)
                f=field(o.name); first=f.first
                assert first.count()
                # Record genuine interaction separately from later semantic task output.
                if o.kind=="radio":
                    for value,_ in o.choices: set_field(o.name,value)
                    set_field(o.name,o.default)
                elif o.kind=="select":
                    for value,_ in o.choices: set_field(o.name,value)
                    set_field(o.name,o.default)
                elif o.kind=="checkbox":
                    original=first.is_checked(); first.set_checked(not original); first.set_checked(original)
                elif o.kind not in ("hidden",):
                    original=first.input_value()
                    trial = "#2646a0" if o.kind=="color" else (o.min if o.min is not None else 2) if o.kind in ("number","range") else "POOL test"
                    set_field(o.name,trial); set_field(o.name,original)
                exercised.add(tool.type+":"+o.name)
            # Restore controlling fields whose dependency activation changed them.
            for o in tool.options:
                if o.show_if:
                    for name in o.show_if:
                        parent=byname.get(name)
                        if parent: set_field(name,parent.default)

        selected=set(filter(None,os.environ.get("POOL_TOOL_FILTER", "").split(",")))
        for original in SCENARIOS:
            if selected and original["type"] not in selected: continue
            case=copy.deepcopy(original); tool=tools[case["type"]]
            errors.clear(); started=time.monotonic()
            print("RUN UI",tool.type,flush=True)
            try:
                r=page.goto(BASE+"/"+tool.slug); assert r.status==200
                page.wait_for_function("()=>window.Tool!==undefined")
                uploads=[{"name":n,"buffer":b,"mimeType":m} for n,b,m in scenario_files(case)]
                if uploads:
                    page.locator("#file-input").set_input_files(uploads)
                    if "locked" in case["files"]:
                        page.locator('.modal input[type="password"]').fill("pool-secret")
                        page.get_by_role("button",name="Unlock",exact=True).click()
                    page.wait_for_function("n=>Tool.readyFiles().length===n",arg=len(uploads))
                if tool.template=="editor.html":
                    page.wait_for_selector(".ed-page canvas.pdf")
                    if tool.type=="edit":
                        page.locator('[data-tool="text"]').click()
                        page.locator(".ed-page").click(position={"x":220,"y":330})
                        page.locator('.obj [contenteditable="true"]').fill("POOL EDITED")
                    elif tool.type=="fillSign": page.locator(".formfield").first.fill("Ada Pool")
                    else:
                        page.locator('[data-tool="field-text"]').click()
                        box=page.locator(".ed-page").bounding_box()
                        x1,y1=box["x"]+80,box["y"]+150
                        x2,y2=box["x"]+min(280,box["width"]-12),box["y"]+190
                        if mobile:
                            cdp=context.new_cdp_session(page)
                            cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x1,"y":y1}]})
                            for fraction in (.25,.5,.75,1): cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x1+(x2-x1)*fraction,"y":y1+(y2-y1)*fraction}]})
                            cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]});cdp.detach()
                        else:
                            page.mouse.move(x1,y1);page.mouse.down()
                            page.mouse.move(x2,y2,steps=5);page.mouse.up()
                        page.locator('[data-p="name"]').fill("pool_new")
                    page.locator('[data-action="save"]').click()
                else:
                    page.locator("#task-form").wait_for(state="visible")
                    options(tool)
                    if tool.type=="crop":
                        case["params"]["unit"]="mm"
                        case["expected"]["crop_width"]=595-20*72/25.4
                    if tool.type=="combineReorder":
                        # All-pages organization here; explicit reorder is covered by API + existing browser suites.
                        case["expected"]={"pages":3}; case["params"]={}
                    for name,value in case["params"].items():
                        if name=="area":
                            wrap=page.locator(".area-wrap"); wrap.wait_for(); wrap.scroll_into_view_if_needed()
                            page.wait_for_function("()=>document.querySelector('.area-wrap canvas')?.width>0")
                            wrap.locator("canvas").evaluate("e=>e.scrollIntoView({block:'start'})")
                            page.evaluate("window.scrollBy(0,-100)")
                            b=wrap.locator("canvas").bounding_box(); x,y,w,h=(value[k] for k in ("x","y","width","height"))
                            page.mouse.move(b["x"]+x*b["width"]/595,b["y"]+y*b["height"]/842);page.mouse.down()
                            page.mouse.move(b["x"]+(x+w)*b["width"]/595,b["y"]+(y+h)*b["height"]/842,steps=5);page.mouse.up()
                        else:
                            option=next((o for o in tool.options if o.name==name),None)
                            if option and option.show_if:
                                for parent,desired in option.show_if.items(): set_field(parent,desired[0] if isinstance(desired,list) else desired)
                            set_field(name,value)
                    page.locator("#submit-btn").click()
                page.wait_for_function("()=>document.querySelector('#stage-result .state-icon.ok, #stage-result .state-icon.err, #toasts .toast.err')",timeout=120000)
                assert page.locator("#stage-result .state-icon.ok").count(), page.locator("#stage-result").inner_text()
                link=page.locator("#stage-result a[download]").first
                response=context.request.get(link.get_attribute("href")); assert response.ok
                name=link.get_attribute("download") or "result.pdf"
                validate_output(case,response.body(),name)
                assert not errors, errors
                results.append({"tool":tool.type,"status":"passed","seconds":round(time.monotonic()-started,2)})
                print("PASS UI",tool.type,flush=True)
            except Exception as e:
                results.append({"tool":tool.type,"status":"failed","error":str(e),"seconds":round(time.monotonic()-started,2)})
                page.screenshot(path=str(OUT/(tool.type+"-ui-failure.png")))
                print("FAIL UI",tool.type,str(e)[:300],flush=True)
        # Responsive shell inventory, separate from desktop document submissions.
        page.set_viewport_size({"width":390,"height":844})
        for slug in ([] if selected else [""]+[t.slug for t in tools.values()]+["workflows","about","privacy","terms","help","developers","html-pdf-api"]):
            errors.clear()
            try:
                r=page.goto(BASE+"/"+slug);assert r.status==200
                page.get_by_role("button",name="All tools",exact=True).click()
                assert page.locator("#mega").is_visible();page.keyboard.press("Escape")
                assert page.locator("#mega").is_hidden()
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2"),"Mobile horizontal overflow"
                assert not errors,errors
                results.append({"page":slug or "/","kind":"mobile-shell","status":"passed"})
            except Exception as e:
                results.append({"page":slug or "/","kind":"mobile-shell","status":"failed","error":str(e)})
                print("FAIL mobile",slug,str(e)[:200],flush=True)
        browser.close()
    report={"viewport":"mobile" if mobile else "desktop","results":results,"declared_options_interacted":sorted(exercised),"expected_options":sum(len(t.options) for t in tools.values())}
    (OUT/("tool-ui-mobile-results.json" if mobile else "tool-ui-results.json")).write_text(json.dumps(report,indent=2),encoding="utf-8")
    failures=[r for r in results if r["status"]!="passed"]
    print(f"{len(results)-len(failures)}/{len(results)} UI/page checks passed; {len(exercised)}/{report['expected_options']} declared fields interacted",flush=True)
    return int(bool(failures) or (not selected and len(exercised)!=report["expected_options"]))


if __name__=="__main__": raise SystemExit(run())
