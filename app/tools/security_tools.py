"""Security & document-properties tools: encrypt, unlock, edit metadata, edit
bookmarks, delete annotations, rename by text."""
from __future__ import annotations

import json
import re
from datetime import datetime

import pikepdf
from pikepdf import Name

from ..jobs import TaskError
from .common import open_pdf, output_name, pages_or_error, save_pdf
from .outlines import Bookmark, read_outline, write_outline
from .registry import Opt, Tool, register

PERMISSIONS = [("print", "Print"), ("degradedprinting", "Print in low quality only"), ("modify", "Change the document"),
               ("copy", "Copy text and images"), ("modifyannotations", "Add comments"), ("fill", "Fill in forms"),
               ("assemble", "Insert, rotate or delete pages")]


# ---------------------------------------------------------------------------
# encrypt / decrypt


def encrypt(ctx):
    user = str(ctx.param("userPassword") or "")
    owner = str(ctx.param("ownerPassword") or "") or user
    if not user and not owner:
        raise TaskError("Enter a password")
    algo = ctx.param("encryptionAlgorithm", "aes_256")
    allowed = ctx.params.get("permissions") or []
    if isinstance(allowed, str):
        allowed = [allowed]
    allowed = set(allowed)
    restrict = ctx.flag("restrictPermissions")
    if not restrict:
        allowed = {k for k, _ in PERMISSIONS}
    perms = pikepdf.Permissions(
        print_lowres="print" in allowed or "degradedprinting" in allowed,
        print_highres="print" in allowed,
        modify_other="modify" in allowed,
        extract="copy" in allowed,
        accessibility=True,
        modify_annotation="modifyannotations" in allowed,
        modify_form="fill" in allowed or "modifyannotations" in allowed,
        modify_assembly="assemble" in allowed,
    )
    r = {"rc4_128": 3, "aes_128": 4, "aes_256": 6}.get(algo, 6)
    enc = pikepdf.Encryption(user=user, owner=owner, R=r, allow=perms, aes=algo != "rc4_128")
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        pdf.save(ctx.output(output_name(ctx, inp)), encryption=enc)
    ctx.remark("Password protection added")


register(Tool(
    type="encrypt", slug="encrypt-pdf", title="Protect PDF", icon="lock", category="security",
    tagline="Add a password and choose what others may do with the document. Uses strong AES-256 encryption.",
    handler=encrypt, keywords="password protect encrypt secure lock",
    options=[
        Opt("userPassword", "Password to open the file", "text", placeholder="Choose a password"),
        Opt("restrictPermissions", "Restrict what people can do even after opening it", "checkbox", advanced=True),
        Opt("ownerPassword", "Permissions password", "text", placeholder="Needed to change permissions", advanced=True,
            show_if={"restrictPermissions": "true"}),
        Opt("encryptionAlgorithm", "Encryption", "radio", [("aes_256", "AES 256-bit"), ("aes_128", "AES 128-bit"), ("rc4_128", "RC4 128-bit (old readers)")],
            "aes_256", advanced=True),
    ],
))


def decrypt(ctx):
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))  # saved without encryption
    ctx.remark("Password and restrictions removed")


register(Tool(
    type="decrypt", slug="unlock-pdf", title="Unlock PDF", icon="unlock", category="security",
    tagline="Remove the password and usage restrictions from a PDF you're allowed to open.",
    handler=decrypt, keywords="remove password decrypt unlock restrictions",
))


# ---------------------------------------------------------------------------
# metadata

META_FIELDS = ["Title", "Author", "Subject", "Keywords", "Creator", "Producer"]


def _pdf_date(value: str) -> str | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y, %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("D:%Y%m%d%H%M%S")
        except ValueError:
            continue
    return None


def edit_metadata(ctx):
    meta = ctx.params.get("metadata") if isinstance(ctx.params.get("metadata"), dict) else {}
    for f in META_FIELDS + ["CreationDate", "ModDate"]:  # flat "metadata.Title" style keys also work
        if f"metadata.{f}" in ctx.params:
            meta[f] = ctx.params[f"metadata.{f}"]
    remove_all = ctx.flag("removeAllMetadata")
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        if remove_all:
            for k in list(pdf.docinfo.keys()):
                del pdf.docinfo[k]
            if "/Metadata" in pdf.Root:
                del pdf.Root["/Metadata"]
        else:
            for k, v in meta.items():
                if k not in META_FIELDS + ["CreationDate", "ModDate"]:
                    continue
                v = "" if v is None else str(v)
                key = Name("/" + k)
                if k in ("CreationDate", "ModDate"):
                    d = _pdf_date(v)
                    if d:
                        pdf.docinfo[key] = d
                    continue
                if v.strip():
                    pdf.docinfo[key] = v.strip()
                elif key in pdf.docinfo:
                    del pdf.docinfo[key]
            if "/Metadata" in pdf.Root:  # stale XMP would override the new values in many readers
                del pdf.Root["/Metadata"]
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("All metadata removed" if remove_all else "Metadata updated")


register(Tool(
    type="editMetadata", slug="edit-pdf-metadata", title="Edit metadata", icon="info", category="security",
    tagline="Change or remove the title, author, subject, keywords and dates stored in a PDF.",
    handler=edit_metadata, page_ui="metadata", multiple=False, keywords="properties author title keywords info",
    options=[Opt(f"metadata.{f}", f, "text") for f in META_FIELDS] + [
        Opt("metadata.CreationDate", "Created", "text", placeholder="YYYY-MM-DD HH:MM"),
        Opt("metadata.ModDate", "Modified", "text", placeholder="YYYY-MM-DD HH:MM"),
        Opt("removeAllMetadata", "Remove all metadata instead", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# bookmarks


def parse_outline_text(text: str, total: int) -> list[Bookmark]:
    """Lines like '  Section title | 4'. Two spaces (or a tab) of indent per level."""
    root: list[Bookmark] = []
    stack: list[tuple[int, Bookmark]] = []
    for n, raw in enumerate((text or "").splitlines(), 1):
        if not raw.strip():
            continue
        expanded = raw.replace("\t", "  ")
        level = (len(expanded) - len(expanded.lstrip(" "))) // 2
        title, sep, page = expanded.strip().rpartition("|")
        if not sep:
            raise TaskError(f"Line {n}: write bookmarks as 'Title | page number'")
        try:
            p = int(page.strip())
        except ValueError:
            raise TaskError(f"Line {n}: '{page.strip()}' is not a page number") from None
        if not 1 <= p <= total:
            raise TaskError(f"Line {n}: page {p} does not exist (the document has {total} pages)")
        b = Bookmark(title.strip(), p - 1)
        while stack and stack[-1][0] >= level:
            stack.pop()
        (stack[-1][1].children if stack else root).append(b)
        stack.append((level, b))
    return root


def outline_to_text(bookmarks: list[Bookmark], level: int = 0) -> str:
    lines = []
    for b in bookmarks:
        lines.append(f"{'  ' * level}{b.title} | {(b.page or 0) + 1}")
        if b.children:
            lines.append(outline_to_text(b.children, level + 1))
    return "\n".join(lines)


def edit_bookmarks(ctx):
    data = ctx.params.get("jsonData")
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        total = len(pdf.pages)
        if data:
            items = json.loads(data) if isinstance(data, str) else data
            bookmarks = _from_json(items, total)
        else:
            bookmarks = parse_outline_text(ctx.param("bookmarks") or "", total)
        write_outline(pdf, bookmarks)
        if bookmarks:
            pdf.Root.PageMode = Name.UseOutlines
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark("Bookmarks saved")


def _from_json(items, total):
    out = []
    for it in items or []:
        p = int(it.get("page", 1))
        if 1 <= p <= total:
            out.append(Bookmark(str(it.get("title", "")), p - 1, _from_json(it.get("children"), total)))
    return out


register(Tool(
    type="editBookmarks", slug="pdf-bookmarks", title="Edit bookmarks", icon="list", category="edit",
    tagline="Add, rename, nest or remove the bookmarks shown in a PDF reader's sidebar.",
    handler=edit_bookmarks, page_ui="bookmarks", multiple=False, keywords="outline table of contents navigation",
    options=[Opt("bookmarks", "Bookmarks", "textarea",
                 help="One bookmark per line as “Title | page”. Indent with two spaces to nest under the line above.")],
))


# ---------------------------------------------------------------------------
# delete annotations

ANNOT_TYPES = [("highlight", "Highlights"), ("underline", "Underlines"), ("strikeout", "Strike-throughs"), ("ink", "Drawings"),
               ("text", "Notes"), ("freetext", "Text boxes"), ("square", "Rectangles"), ("circle", "Ellipses"), ("line", "Lines"),
               ("polygon", "Polygons"), ("polyline", "Polylines"), ("stamp", "Stamps"), ("link", "Links"), ("popup", "Pop-ups")]


def delete_annotations(ctx):
    kinds = ctx.params.get("annotationTypes") or ["all"]
    if isinstance(kinds, str):
        kinds = [kinds]
    kinds = {k.lower() for k in kinds}
    removed = 0
    for inp in ctx.inputs:
        pdf = open_pdf(inp)
        for i in pages_or_error(ctx.param("pages"), len(pdf.pages)):
            page = pdf.pages[i - 1].obj
            annots = page.get("/Annots")
            if not isinstance(annots, pikepdf.Array):
                continue
            keep = []
            for a in annots:
                sub = str(a.get("/Subtype", "")).lstrip("/").lower()
                if sub == "widget":
                    keep.append(a)  # form fields are not annotations to the user
                elif "all" in kinds or sub in kinds:
                    removed += 1
                else:
                    keep.append(a)
            page.Annots = pikepdf.Array(keep)
        save_pdf(pdf, ctx.output(output_name(ctx, inp)))
    ctx.remark(f"Removed {removed} annotation{'s' if removed != 1 else ''}")


register(Tool(
    type="deleteAnnotations", slug="delete-pdf-annotations", title="Delete annotations", icon="eraser", category="edit",
    tagline="Remove comments, highlights, drawings, links and other annotations in bulk.",
    handler=delete_annotations, keywords="remove comments highlights markup clean",
    options=[
        Opt("annotationTypes", "Remove", "radio", [("all", "All annotations"), ("highlight", "Highlights"), ("link", "Links"),
            ("ink", "Drawings"), ("text", "Notes")], "all"),
        Opt("pages", "Pages", "pages", placeholder="all pages", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# rename by text


def rename_by_text(ctx):
    import pdfplumber

    pattern = (ctx.param("renamePattern") or "[TEXT]").strip() or "[TEXT]"
    area = ctx.params.get("area") if isinstance(ctx.params.get("area"), dict) else None
    for n, inp in enumerate(ctx.inputs, 1):
        with pdfplumber.open(str(inp.path), password=inp.password or "") as doc:
            if not doc.pages:
                continue
            page = doc.pages[0]
            if area:
                x, y = float(area.get("x", 0)), float(area.get("y", 0))
                box = (max(0, x), max(0, y), min(float(page.width), x + float(area.get("width", 0))),
                       min(float(page.height), y + float(area.get("height", 0))))
                text = page.within_bbox(box).extract_text() if box[2] > box[0] and box[3] > box[1] else ""
            else:
                text = (page.extract_text() or "").strip().splitlines()[:1]
                text = text[0] if text else ""
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            ctx.warn(f"No text found for '{inp.name}'; kept its name")
            text = inp.stem
        name = (pattern.replace("[TEXT]", text).replace("[BASENAME]", inp.stem).replace("[FILENUMBER]", str(n))
                .replace("[DATE]", datetime.now().strftime("%Y-%m-%d")))
        name = re.sub(r'[\\/:*?"<>|]+', "_", name)[:150].strip() or inp.stem
        ctx.output(name + ".pdf").write_bytes(inp.path.read_bytes())
    ctx.remark("Files renamed")


register(Tool(
    type="renameByText", slug="rename-pdf", title="Rename by text", icon="rename", category="organize",
    tagline="Name each PDF after text it contains, such as an invoice number in a fixed spot.",
    handler=rename_by_text, page_ui="area", keywords="rename filename invoice batch",
    options=[Opt("renamePattern", "New name", "text", default="[TEXT]", help="Tokens: [TEXT] [BASENAME] [FILENUMBER] [DATE]")],
))
