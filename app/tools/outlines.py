"""Reading and copying bookmarks (the document outline) between PDFs."""
from __future__ import annotations

from dataclasses import dataclass, field

import pikepdf


@dataclass
class Bookmark:
    title: str
    page: int | None  # 0-based page index in its document, None if unresolved
    children: list["Bookmark"] = field(default_factory=list)
    level: int = 1


def _objgen_index(pdf: pikepdf.Pdf) -> dict[tuple[int, int], int]:
    return {p.obj.objgen: i for i, p in enumerate(pdf.pages)}


def _resolve_dest(pdf: pikepdf.Pdf, dest, index: dict) -> int | None:
    try:
        if isinstance(dest, (pikepdf.String, str)) or isinstance(dest, pikepdf.Name):
            key = str(dest)
            names = pdf.Root.get("/Names")
            if names is not None and "/Dests" in names:
                nt = pikepdf.NameTree(names.Dests)
                if key in nt:
                    dest = nt[key]
                elif key.lstrip("/") in nt:
                    dest = nt[key.lstrip("/")]
            if isinstance(dest, (pikepdf.String, pikepdf.Name, str)) and "/Dests" in pdf.Root:
                dest = pdf.Root.Dests.get("/" + key.lstrip("/"))
        if isinstance(dest, pikepdf.Dictionary) and "/D" in dest:
            dest = dest.D
        if isinstance(dest, pikepdf.Array) and len(dest) > 0:
            target = dest[0]
            if isinstance(target, pikepdf.Dictionary):
                return index.get(target.objgen)
            if isinstance(target, int):
                return int(target)
    except Exception:
        return None
    return None


def read_outline(pdf: pikepdf.Pdf) -> list[Bookmark]:
    index = _objgen_index(pdf)

    def walk(items, level):
        out = []
        for it in items:
            dest = it.destination
            if dest is None and it.action is not None and it.action.get("/S") == "/GoTo":
                dest = it.action.get("/D")
            out.append(Bookmark(str(it.title or ""), _resolve_dest(pdf, dest, index) if dest is not None else None,
                                walk(it.children, level + 1), level))
        return out

    try:
        with pdf.open_outline() as outline:
            return walk(outline.root, 1)
    except Exception:
        return []


def flatten(bookmarks: list[Bookmark]) -> list[Bookmark]:
    out = []
    for b in bookmarks:
        out.append(b)
        out.extend(flatten(b.children))
    return out


def remap(bookmarks: list[Bookmark], page_map: dict[int, int]) -> list[Bookmark]:
    """Keep bookmarks whose page is in page_map (old index -> new index); children of dropped ones are promoted."""
    out = []
    for b in bookmarks:
        kids = remap(b.children, page_map)
        if b.page is not None and b.page in page_map:
            out.append(Bookmark(b.title, page_map[b.page], kids, b.level))
        else:
            out.extend(kids)
    return out


def write_outline(pdf: pikepdf.Pdf, bookmarks: list[Bookmark], append: bool = False) -> None:
    def build(items):
        out = []
        for b in items:
            if b.page is None:
                continue
            oi = pikepdf.OutlineItem(b.title, b.page)
            oi.children.extend(build(b.children))
            out.append(oi)
        return out

    with pdf.open_outline() as outline:
        if not append:
            outline.root.clear()
        outline.root.extend(build(bookmarks))


def drop_outline(pdf: pikepdf.Pdf) -> None:
    if "/Outlines" in pdf.Root:
        del pdf.Root["/Outlines"]
