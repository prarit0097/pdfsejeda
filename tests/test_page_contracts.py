"""Complete page/declared-option/asset contracts, including inventory drift."""
from functools import lru_cache
from html.parser import HTMLParser
import json
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.tools.registry import all_tools
from app.web import INFO_PAGES


class HTML(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.nodes=[]; self.scripts={}; self.current=None; self.select=None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=="select": self.select=attrs.get("name")
        if tag=="option" and self.select: attrs["_select"]=self.select
        self.nodes.append((tag,attrs))
        if tag == "script" and attrs.get("id"):
            self.current=attrs["id"]; self.scripts[self.current]=""

    def handle_endtag(self, tag):
        if tag == "script": self.current=None
        if tag == "select": self.select=None

    def handle_data(self, text):
        if self.current: self.scripts[self.current]+=text


client = TestClient(app)
TOOLS = all_tools()
PAGES = ["/"] + ["/"+t.slug for t in TOOLS] + ["/workflows"] + ["/"+s for s in INFO_PAGES]


@lru_cache(maxsize=200)
def response(path):
    return client.get(path)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_shell_assets_and_navigation(path):
    r=response(path); assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "object-src 'none'" in r.headers["content-security-policy"]
    doc=HTML(r.text)
    assert sum(tag=="h1" for tag,_ in doc.nodes)==1
    ids=[attrs["id"] for _,attrs in doc.nodes if "id" in attrs]
    assert len(ids)==len(set(ids)), f"Duplicate IDs on {path}"
    assert "main" in ids and "all-tools-btn" in ids and "theme-btn" in ids
    for tag,attrs in doc.nodes:
        for key in ("src", "href"):
            link=attrs.get(key, "")
            if link.startswith("/static/"):
                asset=response(link)
                assert asset.status_code == 200, (path,link)
                assert asset.content
        if tag == "a" and attrs.get("href", "").startswith("/"):
            target=urlsplit(attrs["href"]).path
            assert response(target).status_code == 200, (path,target)
        if attrs.get("aria-controls"):
            assert set(attrs["aria-controls"].split()) <= set(ids)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t:t.slug)
def test_tool_configuration_matches_upload_and_task_form(tool):
    doc=HTML(response("/"+tool.slug).text)
    config=json.loads(doc.scripts["tool-config"])
    assert config["type"]==tool.type and config["slug"]==tool.slug
    inputs=[a for t,a in doc.nodes if t=="input" and a.get("id")=="file-input"]
    assert len(inputs)==1
    assert set(inputs[0]["accept"].split(","))=={"."+x for x in tool.accept}
    assert ("multiple" in inputs[0])==tool.multiple


OPTIONS=[(tool,opt) for tool in TOOLS for opt in tool.options]


@pytest.mark.parametrize("tool,opt", OPTIONS, ids=[t.type+":"+o.name for t,o in OPTIONS])
def test_every_declared_option_is_rendered_with_correct_choices(tool,opt):
    doc=HTML(response("/"+tool.slug).text)
    controls=[(tag,a) for tag,a in doc.nodes if tag in ("input","textarea","select") and a.get("name")==opt.name]
    assert controls, (tool.type,opt.name)
    assert all(a.get("aria-label") or a.get("type") in ("radio","checkbox","hidden") for _,a in controls)
    wrappers=[a for _,a in doc.nodes if a.get("data-opt")==opt.name]
    assert len(wrappers)==1
    if opt.show_if: assert json.loads(wrappers[0]["data-show-if"])==opt.show_if
    if opt.kind=="radio":
        assert {a["value"] for _,a in controls}=={str(value) for value,_ in opt.choices}
        selected=[a for _,a in controls if "checked" in a]
        assert len(selected)==1 and selected[0]["value"]==str(opt.default)
    if opt.kind=="checkbox": assert ("checked" in controls[0][1])==(opt.default in (True,"true"))
    if opt.kind=="select":
        choices=[a for tag,a in doc.nodes if tag=="option" and a.get("_select")==opt.name]
        assert [a["value"] for a in choices]==[str(value) for value,_ in opt.choices]
        assert [a["value"] for a in choices if "selected" in a]==[str(opt.default)]
    if opt.kind in ("range","number"):
        a=controls[0][1]
        if opt.min is not None: assert float(a["min"])==float(opt.min)
        if opt.max is not None: assert float(a["max"])==float(opt.max)


def test_error_pages_and_result_expiry_are_real_errors():
    for path in ("/not-a-real-tool", "/unknown/nested/page", "/result", "/result?id=missing"):
        r=client.get(path); assert r.status_code==404
        assert "<html" in r.text
    assert client.get("/static/not-present.js").status_code==404
    assert client.get("/api/not-present").status_code==404


def test_tool_discovery_has_no_missing_or_duplicate_tools():
    data=client.get("/api/tools").json()
    assert len(data)==len(TOOLS)
    assert {t["type"] for t in data}=={t.type for t in TOOLS}
    assert len({t["slug"] for t in data})==len(data)
