"""Search discovery contracts: public inventory, identity and private exclusions."""
import json
from html.parser import HTMLParser
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import pytest

from app.config import settings, _site_url
from app.main import app
from app.seo import public_paths
from scripts.submit_indexnow import payload_from_sitemap

client=TestClient(app)
NS="{http://www.sitemaps.org/schemas/sitemap/0.9}"


from qa.seo_html import Head


@pytest.mark.parametrize("path",public_paths())
def test_public_page_search_identity(path):
    r=client.get(path+"?utm_source=test",headers={"host":"untrusted.example"})
    assert r.status_code==200
    h=Head(r.text);canonical=settings.site_url+path
    assert h.canonical==[canonical]
    assert h.h1==1 and settings.app_name in h.title
    assert h.meta["og:title"]==h.title
    assert h.meta["og:description"]==h.meta["description"]
    assert 30<len(h.meta["description"])<=165
    assert h.meta["og:url"]==canonical
    assert h.meta["twitter:card"]=="summary_large_image"
    assert h.meta["og:image"]==settings.site_url+"/static/img/social-card.png"
    assert h.meta["robots"].startswith("index, follow")
    graph=json.loads(h.jsonld[0])["@graph"]
    assert any(node["@type"]=="WebPage" and node["url"]==canonical for node in graph)
    assert "aggregateRating" not in h.jsonld[0] and '"review"' not in h.jsonld[0]
    if path.startswith("/guides/"):
        article=next(n for n in graph if n["@type"]=="Article")
        assert article["datePublished"]<=article["dateModified"]


def test_sitemap_matches_only_public_pages_and_unique_metadata():
    r=client.get("/sitemap.xml");assert r.status_code==200 and "xml" in r.headers["content-type"]
    root=ET.fromstring(r.content)
    urls=[n.text for n in root.findall(NS+"url/"+NS+"loc")]
    assert urls==[settings.site_url+p for p in public_paths()]
    assert len(urls)==56==len(set(urls))
    heads=[Head(client.get(p).text) for p in public_paths()]
    assert len({h.title for h in heads})==len(heads)
    assert len({h.meta["description"] for h in heads})==len(heads)
    robots=client.get("/robots.txt");assert robots.status_code==200
    assert f"Sitemap: {settings.site_url}/sitemap.xml" in robots.text
    assert "Disallow: /api/" in robots.text and "Disallow: /result" in robots.text


@pytest.mark.parametrize("path",["/unknown-tool","/guides/unknown","/result?id=missing","/api/tools","/api/tasks/missing"])
def test_private_and_error_pages_not_indexed(path):
    r=client.get(path,follow_redirects=False)
    assert "noindex" in r.headers["x-robots-tag"]
    if r.headers["content-type"].startswith("text/html"):
        h=Head(r.text);assert not h.canonical and "noindex" in h.meta["robots"]


@pytest.mark.parametrize("key,status",[("",404),("bad/key",404),("test-ownership-key-123",200)])
def test_ownership_file(monkeypatch,key,status):
    monkeypatch.setattr(settings,"indexnow_key",key)
    r=client.get("/indexnow-key.txt");assert r.status_code==status
    assert "noindex" in r.headers["x-robots-tag"]
    if status==200: assert r.text==key


def test_verification_tokens_are_escaped_and_home_only(monkeypatch):
    token='test"><script>alert(1)</script>'
    monkeypatch.setattr(settings,"google_site_verification",token)
    monkeypatch.setattr(settings,"bing_site_verification","bing-test-token")
    r=client.get("/");h=Head(r.text)
    assert h.meta["google-site-verification"]==token and h.meta["msvalidate.01"]=="bing-test-token"
    assert '<script>alert(1)</script>' not in r.text
    assert "google-site-verification" not in client.get("/guides").text


@pytest.mark.parametrize("value",["ftp://example.com","https://a.com/path","https://a.com?x=1","https://a.com#x","https://a:b@a.com","https://a.com:99999","https://a.com\n.evil.com","/relative"])
def test_invalid_canonical_origins(value):
    with pytest.raises(ValueError):_site_url(value)


def test_origin_normalization_and_social_image():
    assert _site_url(" https://pdf.example.com/ ")=="https://pdf.example.com"
    data=client.get("/static/img/social-card.png").content
    assert data[:8]==b"\x89PNG\r\n\x1a\n" and struct.unpack(">II",data[16:24])==(1200,630)


def test_indexnow_uses_verified_origin_and_public_inventory():
    payload=payload_from_sitemap(client.get("/sitemap.xml").content,settings.site_url,"test-ownership-key")
    assert len(payload["urlList"])==56
    assert payload["keyLocation"]==settings.site_url+"/indexnow-key.txt"


@pytest.mark.parametrize("url",["https://evil.example/","https://pdf.praritsidana.com/api/files","https://pdf.praritsidana.com/result?id=1","https://pdf.praritsidana.com/%61pi/files","https://pdf.praritsidana.com/?q=x",None])
def test_indexnow_rejects_nonpublic_urls(url):
    root=ET.Element("urlset",xmlns=NS[1:-1]);item=ET.SubElement(root,"url");ET.SubElement(item,"loc").text=url
    with pytest.raises(ValueError):payload_from_sitemap(ET.tostring(root),"https://pdf.praritsidana.com","test-ownership-key")
