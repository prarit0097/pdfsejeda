"""Server-rendered search metadata and canonical public URL inventory."""
from .config import settings
from .content import GUIDES
from .tools.registry import all_tools


INFO_DESCRIPTIONS = {
    "about": "About Prarit Sidana PDF: online PDF editing, merging, compression, conversion and signing, with server processing and automatic file expiry.",
    "privacy": "How Prarit Sidana PDF handles uploaded documents, result links, passwords, browser drafts and automatic file expiry. Read before sharing sensitive files.",
    "terms": "Terms for using Prarit Sidana PDF, including document ownership, acceptable use, processing limits and service availability.",
    "help": "Get help with PDF uploads, passwords, page selection, editing, signatures, OCR, result downloads and file expiry in Prarit Sidana PDF.",
    "developers": "Learn the Prarit Sidana PDF API: upload files, submit PDF tasks, poll results and download outputs. Includes request examples and capability-link security.",
    "html-pdf-api": "Turn HTML into PDF through the Prarit Sidana PDF API. Learn request options, result polling, URL restrictions and download handling.",
    "workflows": "Save reusable PDF workflows: chain tools such as compress, flatten and page numbering, then run the same steps on new documents.",
    "guides": "Practical PDF guides for compressing files, adding signatures, merging documents and making scanned PDFs searchable. Clear steps and honest trade-offs.",
}
INFO_TITLES = {"about":"About", "privacy":"Privacy", "terms":"Terms of use", "help":"PDF Help & FAQ", "developers":"PDF API for Developers", "html-pdf-api":"HTML to PDF API", "workflows":"Reusable PDF Workflows", "guides":"Practical PDF Guides"}


def public_paths():
    return ["/"] + ["/"+t.slug for t in all_tools()] + ["/"+slug for slug in INFO_TITLES] + ["/guides/"+slug for slug in GUIDES]


def page_metadata(path, status=200, tool=None):
    indexable = status==200 and path in public_paths()
    name=settings.app_name
    title=f"Free PDF Tools: Edit, Merge & Compress | {name}"
    description=f"Edit, merge, compress, convert and sign PDFs online with {name}. 43 tools, no sign-up and automatic file expiry."
    label="Home"
    article=None
    if tool:
        label=tool.title
        title=f"{tool.title} Online | {name}"
        description=f"{tool.tagline} Online, no sign-up."
    elif path.startswith("/guides/"):
        article=GUIDES.get(path.removeprefix("/guides/"))
        if article: label=article["title"];title=f"{label} | {name}";description=article["description"]
    elif path.strip("/") in INFO_TITLES:
        slug=path.strip("/");label=INFO_TITLES[slug];title=f"{label} | {name}";description=INFO_DESCRIPTIONS[slug].replace("Prarit Sidana PDF",name)
    if not indexable: title=f"Page unavailable | {name}";description="This page is unavailable. Choose a PDF tool from the home page."
    if len(description)>165: description=description[:162].rsplit(" ",1)[0]+"\u2026"
    canonical=settings.site_url+path if indexable else None
    publisher={"@type":"Organization","@id":settings.site_url+"/#organization","name":name,"url":settings.site_url+"/","logo":{"@type":"ImageObject","url":settings.site_url+"/static/img/logo.svg"}}
    graph=[publisher,{"@type":"WebSite","@id":settings.site_url+"/#website","name":name,"url":settings.site_url+"/","publisher":{"@id":publisher["@id"]}}]
    if indexable:
        graph.append({"@type":"WebPage","@id":canonical+"#webpage","name":title,"description":description,"url":canonical,"isPartOf":{"@id":settings.site_url+"/#website"},"inLanguage":"en"})
        if path!="/":
            crumbs=[{"@type":"ListItem","position":1,"name":"Home","item":settings.site_url+"/"}]
            if article: crumbs.append({"@type":"ListItem","position":2,"name":"Guides","item":settings.site_url+"/guides"})
            crumbs.append({"@type":"ListItem","position":len(crumbs)+1,"name":label,"item":canonical})
            graph.append({"@type":"BreadcrumbList","itemListElement":crumbs})
        if article:
            graph.append({"@type":"Article","headline":article["title"],"description":description,"url":canonical,"mainEntityOfPage":canonical,"publisher":{"@id":publisher["@id"]},"author":{"@id":publisher["@id"]},"datePublished":article["published"],"dateModified":article["updated"],"image":settings.site_url+"/static/img/social-card.png"})
    return {"title":title,"description":description,"canonical":canonical,"indexable":indexable,"robots":"index, follow, max-image-preview:large" if indexable else "noindex, nofollow","image":settings.site_url+"/static/img/social-card.png","type":"article" if article else "website","jsonld":{"@context":"https://schema.org","@graph":graph} if indexable else None}
