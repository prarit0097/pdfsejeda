"""HTML page routes: home, one page per tool, static info pages."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .tools.registry import CATEGORIES, all_tools, by_slug
from .content import GUIDES
from .seo import page_metadata, public_paths

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.globals.update(app_name=settings.app_name, categories=CATEGORIES,
                             max_file_mb=settings.max_file_mb, ttl_hours=round(settings.file_ttl_seconds / 3600, 1))

def accept_attr(tool) -> str:
    return ",".join("." + e for e in tool.accept)


def accept_label(tool) -> str:
    exts = [e.upper() for e in tool.accept if e not in ("jpeg", "tif")]
    if len(exts) <= 2:
        return " or ".join(exts)
    return ", ".join(exts[:-1]) + " or " + exts[-1]


templates.env.globals.update(accept_attr=accept_attr, accept_label=accept_label)

INFO_PAGES ={"about": "About", "privacy": "Privacy", "terms": "Terms of use", "help": "Help & FAQ",
             "developers": "Developer API", "html-pdf-api": "HTML to PDF API"}


def _tools_by_category():
    tools = all_tools()
    groups = {key: [] for key, _ in CATEGORIES}
    for t in tools:
        if t.popular:
            groups["popular"].append(t)
        groups.setdefault(t.category, []).append(t)
        for extra in t.extra_categories:
            groups.setdefault(extra, []).append(t)
    return groups


def _render(request: Request, name: str, status: int = 200, **ctx):
    ctx.setdefault("all_tools", all_tools())
    ctx.setdefault("seo",page_metadata(request.url.path,status,ctx.get("tool")))
    ctx.setdefault("google_site_verification",settings.google_site_verification)
    ctx.setdefault("bing_site_verification",settings.bing_site_verification)
    return templates.TemplateResponse(request, name, ctx, status_code=status)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _render(request, "index.html", groups=_tools_by_category(), guides=GUIDES)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /result\nSitemap: {settings.site_url}/sitemap.xml\n",headers={"Cache-Control":"public, max-age=3600"})


@router.get("/sitemap.xml")
async def sitemap():
    from xml.etree.ElementTree import Element, SubElement, tostring
    root=Element("urlset",xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for path in public_paths():
        item=SubElement(root,"url");SubElement(item,"loc").text=settings.site_url+path
        if path.startswith("/guides/"): SubElement(item,"lastmod").text=GUIDES[path.removeprefix("/guides/")]["updated"]
    return Response(tostring(root,encoding="utf-8",xml_declaration=True),media_type="application/xml",headers={"Cache-Control":"public, max-age=3600"})


@router.get("/indexnow-key.txt", response_class=PlainTextResponse)
async def indexnow_key():
    import re
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}",settings.indexnow_key):
        return PlainTextResponse("Not configured",status_code=404,headers={"X-Robots-Tag":"noindex"})
    return PlainTextResponse(settings.indexnow_key,headers={"X-Robots-Tag":"noindex","Cache-Control":"public, max-age=3600"})


@router.get("/guides", response_class=HTMLResponse)
async def guides(request: Request):
    return _render(request,"guides.html",guides=GUIDES)


@router.get("/guides/{slug}", response_class=HTMLResponse)
async def guide(request: Request, slug: str):
    article=GUIDES.get(slug)
    if not article: return _render(request,"404.html",status=404)
    return _render(request,"guide.html",guide=article)


@router.get("/workflows", response_class=HTMLResponse)
async def workflows(request: Request):
    return _render(request, "workflows.html")


@router.get("/result", response_class=HTMLResponse)
async def result(request: Request, id: str = ""):
    """A shareable result entry point; the existing tool controller handles polling and expiry."""
    from .jobs import queue
    from .tools.registry import get_tool

    task = queue.get(id)
    if not task:
        return _render(request, "expired.html", status=404)
    return RedirectResponse(f"/{get_tool(task.type).slug}#results-{task.id}", status_code=303,
                            headers={"Cache-Control": "no-store, private", "X-Robots-Tag": "noindex, nofollow"})


@router.get("/{slug}", response_class=HTMLResponse)
async def page(request: Request, slug: str):
    if slug in INFO_PAGES:
        template = "info/developers.html" if slug in ("developers", "html-pdf-api") else f"info/{slug}.html"
        return _render(request, template, title=INFO_PAGES[slug], html_api=slug == "html-pdf-api")
    tool = by_slug(slug)
    if not tool:
        return _render(request, "404.html", status=404)
    related = [t for t in all_tools() if t.category == tool.category and t.slug != tool.slug][:6]
    related_guides={slug:g for slug,g in GUIDES.items() if any(s==tool.slug for s,_ in g["related_tools"])}
    return _render(request, tool.template or "tool.html", tool=tool, related=related, related_guides=related_guides)
