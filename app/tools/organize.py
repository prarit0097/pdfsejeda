"""Merge & organize tools: merge, split (4 ways + down the middle), alternate mix,
extract, delete, organize (combineReorder), rotate."""
from __future__ import annotations

import io
import math
from contextlib import ExitStack
import re
import time

import pikepdf
from pikepdf import Name

from ..jobs import TaskError
from .common import (PAGE_SIZES_PT, open_pdf, output_name, page_box, pages_or_error, rotation, save_pdf)
from .draw import draw_text, invert, new_blank_page, place_page, stamp, user_to_visible, visible_size
from .imaging import is_image, image_to_pdf
from .outlines import Bookmark, drop_outline, flatten, read_outline, remap, write_outline
from .registry import IMAGES, PDF, Opt, Tool, register

# ---------------------------------------------------------------------------
# helpers


def _open_any(inp):
    """PDF inputs open directly; images become one page per frame."""
    if is_image(inp.name, inp.path):
        return image_to_pdf(inp.path, "a4")
    return open_pdf(inp)


def copy_pages(dst: pikepdf.Pdf, src: pikepdf.Pdf, indices: list[int]) -> list[int]:
    """Append src pages (0-based indices, repeats allowed) to dst. Returns their new indices."""
    out, seen = [], set()
    for i in indices:
        if i in seen:  # the same foreign page twice: duplicate it first
            dup = src.make_indirect(pikepdf.Dictionary({k: v for k, v in src.pages[i].obj.items() if k != "/Parent"}))
            dst.pages.append(pikepdf.Page(dup))
        else:
            dst.pages.append(src.pages[i])
            seen.add(i)
        out.append(len(dst.pages) - 1)
    return out


def duplicate_page(pdf: pikepdf.Pdf, page: pikepdf.Page) -> pikepdf.Page:
    d = pdf.make_indirect(pikepdf.Dictionary({k: v for k, v in page.obj.items() if k not in ("/Parent", "/Annots")}))
    return pikepdf.Page(d)


def set_visible_crop(page: pikepdf.Page, vx0: float, vy0: float, vx1: float, vy1: float) -> None:
    """Set the CropBox from a rectangle given in displayed coordinates."""
    m = invert(user_to_visible(page))
    pts = [(vx0, vy0), (vx1, vy1), (vx0, vy1), (vx1, vy0)]
    xs = [m[0] * x + m[2] * y + m[4] for x, y in pts]
    ys = [m[1] * x + m[3] * y + m[5] for x, y in pts]
    page.obj.CropBox = pikepdf.Array([float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))])


def _naming(ctx, inp, n: int, page: int | None = None, bookmark: str = "", text: str = "") -> str:
    pattern = (ctx.param("outputFilenamePattern") or "").strip()
    if not pattern:
        base = f"{inp.stem}-{n}"
        if bookmark:
            base = re.sub(r'[\\/:*?"<>|]+', "_", bookmark)[:80] or base
        if text:
            base = re.sub(r'[\\/:*?"<>|\s]+', "_", text)[:80] or base
        return base + ".pdf"
    name = (pattern.replace("[BASENAME]", inp.stem).replace("[CURRENTPAGE]", str(page or n))
            .replace("[FILENUMBER]", str(n)).replace("[TIMESTAMP]", time.strftime("%Y%m%d%H%M%S"))
            .replace("[BOOKMARK_NAME]", bookmark).replace("[BOOKMARK_NAME_STRICT]", bookmark)
            .replace("[TEXT]", text))
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def _save_chunk(ctx, src: pikepdf.Pdf, indices: list[int], name: str, keep_outline: bool, outline) -> None:
    dst = pikepdf.new()
    new_idx = copy_pages(dst, src, indices)
    if keep_outline and outline:
        write_outline(dst, remap(outline, dict(zip(indices, new_idx))))
    save_pdf(dst, ctx.output(name))


# ---------------------------------------------------------------------------
# merge


def merge(ctx):
    outline_policy = ctx.param("outlinePolicy", "retain")
    toc_policy = ctx.param("tocPolicy", "none")
    blank_if_odd = ctx.flag("blankPageIfOdd")
    normalize = ctx.flag("normalizePageSizes")
    footer = ctx.flag("filenameFooter")
    form_policy = ctx.param("acroFormPolicy", "merge")
    rotations = ctx.params.get("rotations") or []
    dst = pikepdf.new()
    bookmarks: list[Bookmark] = []
    starts: list[tuple[str, int, int]] = []  # (label, first page, page count)
    by_name: dict[str, pikepdf.Object] = {}
    fields: list = []
    form_res: dict = {}  # /DR and /DA collected from the inputs' AcroForms
    for n, inp in enumerate(ctx.inputs):
        ctx.check_cancelled()
        src = _open_any(inp)
        start = len(dst.pages)
        idx = copy_pages(dst, src, list(range(len(src.pages))))
        rot = _quarter(rotations[n] if n < len(rotations) else 0)
        if rot:
            for i in idx:
                dst.pages[i].obj.Rotate = (rotation(dst.pages[i]) + rot) % 360
        label = inp.stem
        if toc_policy == "doc_titles":
            try:
                label = str(src.docinfo.get("/Title") or "") or inp.stem
            except Exception:
                pass
        starts.append((label, start, len(idx)))
        src_outline = read_outline(src) if outline_policy != "discard" else []
        mapped = remap(src_outline, {i: start + i for i in range(len(src.pages))})
        if outline_policy == "retain":
            bookmarks.extend(mapped)
        elif outline_policy == "one_entry_each_doc":
            bookmarks.append(Bookmark(inp.stem, start))
        elif outline_policy == "retain_as_one_entry":
            bookmarks.append(Bookmark(inp.stem, start, mapped))
        if "/AcroForm" in src.Root and "/Fields" in src.Root.AcroForm:
            _merge_form_resources(dst, src, form_res)
            for f in _collect_copied_fields(dst, idx):
                name = str(f.get("/T", ""))
                if name and name in by_name:
                    if form_policy == "merge" and _join_fields(dst, by_name, fields, name, f):
                        continue  # same name: one field with several widgets (they share the value)
                    k = n + 1
                    while f"{name}_{k}" in by_name:
                        k += 1
                    name = f"{name}_{k}"
                    f.T = pikepdf.String(name)
                by_name[name] = f
                fields.append(f)
        if blank_if_odd and len(idx) % 2 == 1 and n < len(ctx.inputs) - 1:
            w, h = visible_size(dst.pages[-1])
            new_blank_page(dst, w, h)
    if normalize and len(dst.pages) > 1:
        _normalize_widths(dst)
    if footer:
        for label, first, count in starts:
            for i in range(first, first + count):
                _footer_text(dst, dst.pages[i], label)
    if fields and form_policy != "none":
        af = pikepdf.Dictionary(Fields=pikepdf.Array(fields), NeedAppearances=True)
        if "DR" in form_res:
            af.DR = form_res["DR"]
        if "DA" in form_res:
            af.DA = form_res["DA"]
        dst.Root.AcroForm = af
        if form_policy == "flatten":
            _flatten_widgets(dst)
    elif form_policy == "none":
        _strip_widgets(dst)
    if toc_policy in ("file_names", "doc_titles"):
        # first file as cover: the contents go after it and don't list it
        cover = ctx.flag("firstInputCoverTitle") and len(starts) > 1
        at = starts[1][1] if cover else 0
        toc_pages = _insert_toc(dst, starts[1:] if cover else starts, at)
        bookmarks = remap(bookmarks, {i: (i + toc_pages if i >= at else i) for i in range(len(dst.pages))})
    if bookmarks:
        write_outline(dst, bookmarks)
    name = (ctx.param("outputFilename") or "").strip()
    if name:
        name = name if name.lower().endswith(".pdf") else name + ".pdf"
    else:
        name = f"{ctx.inputs[0].stem}-merged.pdf" if len(ctx.inputs) > 1 else output_name(ctx, ctx.inputs[0])
    save_pdf(dst, ctx.output(name))
    ctx.remark(f"Merged {len(ctx.inputs)} file{'s' if len(ctx.inputs) != 1 else ''} into {len(dst.pages)} pages")


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _quarter(deg, what: str = "Rotation") -> int:
    """A rotation in degrees, normalised to 0/90/180/270. /Rotate must be a multiple of 90."""
    d = _int(deg, 0)
    if d % 90:
        raise TaskError(f"{what} must be a multiple of 90 degrees (got {deg})")
    return d % 360


def _collect_copied_fields(pdf, page_indices):
    roots = []
    seen = set()
    for i in page_indices:
        for annot in pdf.pages[i].obj.get("/Annots", []) or []:
            if annot.get("/Subtype") != Name.Widget:
                continue
            node = annot
            while "/Parent" in node and "/T" not in node:
                node = node.Parent
            while "/Parent" in node and "/T" in node.Parent:
                node = node.Parent
            if node.objgen not in seen:
                seen.add(node.objgen)
                roots.append(node)
    return roots


_FIELD_KEYS = ("/FT", "/Ff", "/V", "/DV", "/T", "/TU", "/TM", "/Opt", "/MaxLen", "/Q", "/TI", "/I")


def _merge_form_resources(dst, src, res: dict) -> None:
    """Carry the default resources (/DR fonts) and default appearance (/DA) over to the merged form,
    otherwise widgets whose /DA names a font from /DR have no font to regenerate appearances with."""
    src_acroform = src.Root.AcroForm
    if "/DA" in src_acroform and "DA" not in res:
        res["DA"] = pikepdf.String(bytes(src_acroform.DA))
    dr = src_acroform.get("/DR")
    if not isinstance(dr, pikepdf.Dictionary):
        return
    dr = dst.copy_foreign(dr if dr.is_indirect else src.make_indirect(dr))
    if "DR" not in res:
        res["DR"] = dr
        return
    into = res["DR"]
    for cat, sub in dr.items():  # /Font, /XObject, ...: add missing names
        if cat not in into:
            into[cat] = sub
        elif isinstance(sub, pikepdf.Dictionary) and isinstance(into[cat], pikepdf.Dictionary):
            for k, v in sub.items():
                if k not in into[cat]:
                    into[cat][k] = v


def _is_terminal(field) -> bool:
    kids = field.get("/Kids")
    return kids is None or all("/T" not in k for k in kids)


def _join_fields(dst, by_name: dict, fields: list, name: str, new) -> bool:
    """Make `new` (a root field with the same name as an earlier one) extra widgets of that field.
    Returns False when they can't be joined (different types, or hierarchical fields)."""
    old = by_name[name]
    if old.get("/FT") != new.get("/FT") or not _is_terminal(old) or not _is_terminal(new):
        return False
    if "/Kids" not in old:  # a combined field+widget dictionary: split off a parent field
        parent = dst.make_indirect(pikepdf.Dictionary({k: old[k] for k in _FIELD_KEYS if k in old}))
        if "/DA" in old:
            parent.DA = old.DA
        for k in _FIELD_KEYS:
            if k in old:
                del old[k]
        old.Parent = parent
        parent.Kids = pikepdf.Array([old])
        at = next(i for i, f in enumerate(fields) if f.objgen == old.objgen)
        fields[at] = parent
        by_name[name] = old = parent
    if "/Kids" in new:
        widgets = list(new.Kids)
    else:  # field+widget in one dictionary: keep only the widget part
        for k in _FIELD_KEYS:
            if k in new:
                del new[k]
        widgets = [new]
    for w in widgets:
        w.Parent = old
        old.Kids.append(w)
    return True


def _flatten_widgets(pdf) -> None:
    """Burn form fields into the page content; other annotations (links, comments) stay."""
    try:
        pdf.generate_appearance_streams()  # qpdf refuses to flatten while NeedAppearances is set
    except Exception:
        pass
    stash = {}
    for i, page in enumerate(pdf.pages):
        annots = page.obj.get("/Annots")
        if isinstance(annots, pikepdf.Array):
            stash[i] = [a for a in annots if a.get("/Subtype") != Name.Widget]
            page.obj.Annots = pikepdf.Array([a for a in annots if a.get("/Subtype") == Name.Widget])
    pdf.flatten_annotations("all")
    for i, keep in stash.items():
        if keep:
            pdf.pages[i].obj.Annots = pikepdf.Array(keep)
        elif "/Annots" in pdf.pages[i].obj:
            del pdf.pages[i].obj["/Annots"]
    if "/AcroForm" in pdf.Root:
        del pdf.Root["/AcroForm"]


def _strip_widgets(pdf):
    for page in pdf.pages:
        if "/Annots" in page.obj:
            keep = [a for a in page.obj.Annots if a.get("/Subtype") != Name.Widget]
            page.obj.Annots = pikepdf.Array(keep)


def _normalize_widths(pdf):
    """Scale every page to the width of the first page, keeping its aspect ratio."""
    target_w, _ = visible_size(pdf.pages[0])
    for i in range(1, len(pdf.pages)):
        page = pdf.pages[i]
        w, h = visible_size(page)
        if abs(w - target_w) < 1:
            continue
        nh = h * target_w / w
        new = new_blank_page(pdf, target_w, nh, index=i + 1)
        place_page(pdf, new, pdf.pages[i], (0, 0, target_w, nh))
        del pdf.pages[i]


def _footer_text(pdf, page, text):
    def draw(c, w, h):
        c.setFillColorRGB(0.35, 0.35, 0.35)
        draw_text(c, w / 2, 12, text, "helvetica", 8, align="center")

    stamp(pdf, page, draw)


def _insert_toc(pdf, starts, at: int = 0) -> int:
    """Insert table-of-contents page(s) before page index `at` with clickable entries.
    `starts` are (label, first page, count) in the document before insertion. Returns pages added."""
    from reportlab.pdfgen import canvas as rl_canvas

    w, h = PAGE_SIZES_PT["a4"]
    per_page = 38
    n_pages = max(1, (len(starts) + per_page - 1) // per_page)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    rects = []
    shift = lambda i: i + n_pages if i >= at else i  # noqa: E731  page index after insertion
    for p in range(n_pages):
        c.setFont("Helvetica-Bold", 18)
        c.drawString(56, h - 72, "Contents")
        y = h - 110
        for label, first, _ in starts[p * per_page:(p + 1) * per_page]:
            label = label if len(label) <= 80 else label[:79] + "…"
            draw_text(c, 56, y, label, "helvetica", 11)
            c.setFont("Helvetica", 11)
            c.drawRightString(w - 56, y, str(shift(first) + 1))
            rects.append((p, (56, y - 3, w - 56, y + 11), first))
            y -= 18
        c.showPage()
    c.save()
    with pikepdf.open(io.BytesIO(buf.getvalue())) as toc:
        for i, page in enumerate(toc.pages):
            pdf.pages.insert(at + i, page)
    for p, (x0, y0, x1, y1), first in rects:
        target = pdf.pages[shift(first)].obj
        annot = pdf.make_indirect(pikepdf.Dictionary(
            Type=Name.Annot, Subtype=Name.Link, Rect=[x0, y0, x1, y1], Border=[0, 0, 0],
            Dest=pikepdf.Array([target, Name.Fit])))
        page = pdf.pages[at + p].obj
        if "/Annots" not in page:
            page.Annots = pikepdf.Array()
        page.Annots.append(annot)
    return n_pages


register(Tool(
    type="merge", slug="merge-pdf", title="Merge PDF", icon="merge", category="organize", popular=True,
    tagline="Combine PDFs and images into one document, in the order you choose.",
    handler=merge, accept=PDF + IMAGES, min_files=1, page_ui="files",
    keywords="combine join append",
    options=[
        Opt("outputFilename", "Output file name", "text", placeholder="merged.pdf", advanced=True),
        Opt("outlinePolicy", "Bookmarks", "radio", [("retain", "Keep all"), ("discard", "Remove all"),
            ("one_entry_each_doc", "One entry per file"), ("retain_as_one_entry", "Keep, grouped by file")],
            "retain", advanced=True),
        Opt("tocPolicy", "Table of contents", "radio", [("none", "None"), ("file_names", "From file names"),
            ("doc_titles", "From document titles")], "none", advanced=True),
        Opt("firstInputCoverTitle", "The first file is a cover: put the table of contents after it", "checkbox",
            advanced=True, show_if={"tocPolicy": ["file_names", "doc_titles"]}),
        Opt("acroFormPolicy", "Form fields", "radio", [("merge", "Merge"), ("merge_renaming", "Merge, rename duplicates"),
            ("flatten", "Flatten"), ("none", "Discard")], "merge", advanced=True),
        Opt("blankPageIfOdd", "Add a blank page after files with an odd page count (for double-sided printing)", "checkbox", advanced=True),
        Opt("normalizePageSizes", "Make all pages the same width as the first", "checkbox", advanced=True),
        Opt("filenameFooter", "Add each file's name in the page footer", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# split by pages


def split_by_pages(ctx):
    keep_outline = not ctx.flag("discardOutline")
    names = ctx.params.get("specificResultFilenames") or []
    for inp in ctx.inputs:
        src = open_pdf(inp)
        total = len(src.pages)
        step = _int(ctx.param("step"), 0)
        spec = ctx.param("pages")
        split_mode = ctx.param("splitMode")
        if split_mode in ("even", "odd"):
            spec, step = split_mode, 0
        elif split_mode == "after":
            step = 0
            if not spec:
                raise TaskError("Choose the pages to split after")
        elif split_mode == "every":
            spec = None
        if spec in ("even", "odd") and not step:
            cuts = [p for p in range(1, total) if (p % 2 == 0) == (spec == "even")]
        elif spec not in (None, "") and not step:
            cuts = [p for p in pages_or_error(spec, total) if p < total]
        else:
            step = max(step, 1)
            cuts = list(range(step, total, step))
        bounds = [0] + cuts + [total]
        outline = read_outline(src) if keep_outline else []
        for n in range(len(bounds) - 1):
            ctx.check_cancelled()
            a, b = bounds[n], bounds[n + 1]
            if a >= b:
                continue
            custom = str(names[n]).strip() if n < len(names) and names[n] else ""
            name = (custom if custom.lower().endswith(".pdf") else custom + ".pdf") if custom else _naming(ctx, inp, n + 1, a + 1)
            _save_chunk(ctx, src, list(range(a, b)), name, keep_outline, outline)
    ctx.remark("Split complete")


register(Tool(
    type="splitByPages", slug="split-pdf", title="Split PDF", icon="split", category="organize", popular=True,
    tagline="Cut a PDF into several files: every page, every few pages, or after the pages you pick.",
    handler=split_by_pages, page_ui="split", keywords="separate burst cut divide",
    options=[
        Opt("splitMode", "How to split", "radio", [("every", "Every N pages"), ("after", "After specific pages"),
            ("even", "After every even page"), ("odd", "After every odd page")], "every"),
        Opt("step", "Pages per file", "number", default=1, min=1, show_if={"splitMode": "every"}),
        Opt("pages", "Split after pages", "pages", placeholder="e.g. 3,7,10", show_if={"splitMode": "after"}),
        Opt("outputFilenamePattern", "File name pattern", "text", placeholder="[BASENAME]-[CURRENTPAGE]",
            help="Tokens: [BASENAME] [CURRENTPAGE] [FILENUMBER] [TIMESTAMP]", advanced=True),
        Opt("discardOutline", "Remove bookmarks from the results", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# split by bookmarks


def split_by_bookmarks(ctx):
    level = _int(ctx.param("bookmarksLevel"), 1) or 1
    expr = (ctx.param("bookmarksExpression") or "").strip()
    include_after = ctx.flag("includePageAfter")
    try:
        rx = re.compile(expr, re.I) if expr else None
    except re.error:
        raise TaskError("The bookmark filter is not a valid regular expression") from None
    for inp in ctx.inputs:
        src = open_pdf(inp)
        total = len(src.pages)
        outline = read_outline(src)
        marks = [b for b in flatten(outline) if b.level == level and b.page is not None and (not rx or rx.search(b.title))]
        if not marks:
            raise TaskError(f"'{inp.name}' has no bookmarks at level {level}" + (" matching the filter" if rx else ""))
        marks.sort(key=lambda b: b.page)
        starts = []
        for b in marks:
            if not starts or b.page != starts[-1][0]:
                starts.append((b.page, b.title))
        if starts[0][0] > 0:
            starts.insert(0, (0, inp.stem))
        for n, (page, title) in enumerate(starts):
            end = starts[n + 1][0] if n + 1 < len(starts) else total
            if include_after and n + 1 < len(starts):
                end = min(end + 1, total)
            indices = list(range(page, max(end, page + 1)))
            _save_chunk(ctx, src, indices, _naming(ctx, inp, n + 1, page + 1, bookmark=title), True, outline)
    ctx.remark("Split by bookmarks complete")


register(Tool(
    type="splitByBookmarks", slug="split-pdf-by-outline", title="Split by bookmarks", icon="bookmark", category="organize",
    tagline="Make one file per chapter, using the bookmarks in the document's outline.",
    handler=split_by_bookmarks, keywords="outline chapters table of contents",
    options=[
        Opt("bookmarksLevel", "Bookmark level", "radio", [("1", "Level 1"), ("2", "Level 2"), ("3", "Level 3")], "1"),
        Opt("bookmarksExpression", "Only bookmarks matching", "text", placeholder="e.g. Chapter", advanced=True,
            help="Text or regular expression. Leave empty for all."),
        Opt("includePageAfter", "Also include the page where the next bookmark starts", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# split by size


def _pdf_size(src, indices) -> int:
    dst = pikepdf.new()
    copy_pages(dst, src, indices)
    buf = io.BytesIO()
    dst.save(buf, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return buf.tell()


def split_by_size(ctx):
    size = ctx.number("size", 1.5)
    unit = (ctx.param("sizeUnit") or "MB").upper()
    limit = int(size * (1024 * 1024 if unit == "MB" else 1024))
    if limit < 10 * 1024:
        raise TaskError("Please choose a size of at least 10 KB")
    for inp in ctx.inputs:
        src = open_pdf(inp)
        total, start, n = len(src.pages), 0, 0
        while start < total:
            ctx.check_cancelled()

            def fits(end):  # pages start..end-1 saved together stay under the limit
                ctx.check_cancelled()
                return _pdf_size(src, list(range(start, end))) <= limit

            # Galloping search for the largest end that fits: O(log n) trial saves per chunk
            # instead of one per page (a 300-page file used to need ~300 full saves).
            lo, step = start + 1, 1  # lo = largest end known to fit (1 page is always taken)
            hi = None                # smallest end known not to fit
            while lo < total:
                probe = min(lo + step, total)
                if fits(probe):
                    lo, step = probe, step * 2
                else:
                    hi = probe
                    break
            if hi is not None:
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if fits(mid):
                        lo = mid
                    else:
                        hi = mid
            end = lo
            n += 1
            if end - start == 1 and not fits(end):
                ctx.warn(f"Page {start + 1} of '{inp.name}' alone is larger than the size limit")
            _save_chunk(ctx, src, list(range(start, end)), _naming(ctx, inp, n, start + 1), False, None)
            start = end
    ctx.remark("Split by size complete")


register(Tool(
    type="splitBySize", slug="split-pdf-by-size", title="Split by size", icon="scale", category="organize",
    tagline="Break a large PDF into smaller files that each stay under a size you choose.",
    handler=split_by_size, keywords="email attachment limit",
    options=[
        Opt("size", "Maximum size per file", "number", default=1.5, min=0.01, step=0.1),
        Opt("sizeUnit", "Unit", "radio", [("MB", "MB"), ("KB", "KB")], "MB"),
    ],
))


# ---------------------------------------------------------------------------
# split by text


def parse_area(raw) -> dict | None:
    """`area` as sent by the page ({x,y,width,height}, strings or numbers). None when missing/empty/invalid."""
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, list) and raw:  # Sejda's rename tool sends `areas: [ {...} ]`
        raw = raw[0]
    if not isinstance(raw, dict):
        return None
    try:
        a = {k: float(raw.get(k) or 0) for k in ("x", "y", "width", "height")}
    except (TypeError, ValueError):
        return None
    return a if a["width"] > 0 and a["height"] > 0 else None


def area_text(pdfium_page, page: pikepdf.Page, area: dict | None) -> str:
    """Text inside `area` (PDF points, top-left origin, in the page as displayed: after /Rotate,
    relative to the CropBox — exactly what PDF.js shows in the browser). Without an area: the
    first non-empty line of the page."""
    tp = pdfium_page.get_textpage()
    try:
        if not area:
            for line in (tp.get_text_range() or "").splitlines():
                if line.strip():
                    return " ".join(line.split())
            return ""
        w, h = visible_size(page)
        x0, x1 = max(0.0, area["x"]), min(w, area["x"] + area["width"])
        top, bottom = max(0.0, area["y"]), min(h, area["y"] + area["height"])
        if x1 <= x0 or bottom <= top:
            return ""
        m = invert(user_to_visible(page))  # displayed (bottom-left origin) -> user space
        pts = [(x0, h - top), (x1, h - bottom)]
        xs = [m[0] * x + m[2] * y + m[4] for x, y in pts]
        ys = [m[1] * x + m[3] * y + m[5] for x, y in pts]
        text = tp.get_text_bounded(left=min(xs), bottom=min(ys), right=max(xs), top=max(ys)) or ""
        return " ".join(text.replace("\x00", "").split())
    finally:
        tp.close()


def iter_area_texts(inp, area: dict | None, pages=None, cancel=None):
    """Yield (0-based page index, text in area) for the pages of a PDF input."""
    from .common import pdfium_doc

    src = open_pdf(inp)
    with pdfium_doc(inp) as doc:
        for i in (pages if pages is not None else range(len(doc))):
            if cancel:
                cancel()
            pg = doc[i]
            try:
                yield i, area_text(pg, src.pages[i], area)
            finally:
                pg.close()


def split_by_text(ctx):
    area = parse_area(ctx.params.get("area"))
    starts_with = (ctx.param("startsWith") or "").strip()
    for inp in ctx.inputs:
        src = open_pdf(inp)
        groups: list[tuple[int, str]] = []
        prev = None
        for i, text in iter_area_texts(inp, area, cancel=ctx.check_cancelled):
            if starts_with and not text.lower().startswith(starts_with.lower()):
                text = ""
            if text and text != prev:
                groups.append((i, text))
                prev = text
        if not groups:
            raise TaskError(f"No text found in the selected area of '{inp.name}'")
        if groups[0][0] > 0:
            groups.insert(0, (0, ""))
        total = len(src.pages)
        for n, (page, text) in enumerate(groups):
            end = groups[n + 1][0] if n + 1 < len(groups) else total
            _save_chunk(ctx, src, list(range(page, end)), _naming(ctx, inp, n + 1, page + 1, text=text), False, None)
    ctx.remark("Split by text complete")


register(Tool(
    type="splitByText", slug="split-pdf-by-text", title="Split by text", icon="text-search", category="organize",
    tagline="Start a new file whenever the text in an area of the page changes, e.g. a new invoice number.",
    handler=split_by_text, page_ui="area", keywords="invoice statement content",
    options=[
        Opt("startsWith", "Only when the text starts with", "text", placeholder="optional", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# split down the middle


def split_down_middle(ctx):
    ratio = ctx.number("ratio", 1.0) or 1.0
    rtl = ctx.flag("rightToLeft")
    auto_exclude = ctx.flag("autoDetectExcludedPages")
    booklet = (ctx.param("repagination") or "") == "last-first" or ctx.params.get("repagination") is True
    mode = ctx.param("mode", "auto")
    for inp in ctx.inputs:
        src = open_pdf(inp)
        total = len(src.pages)
        excluded = set(pages_or_error(ctx.param("excludedPages"), total)) if ctx.param("excludedPages") else set()
        if auto_exclude:
            landscape = sum(1 for p in src.pages if visible_size(p)[0] > visible_size(p)[1])
            majority_landscape = landscape * 2 >= total
            for i, p in enumerate(src.pages):
                w, h = visible_size(p)
                if (w > h) != majority_landscape:
                    excluded.add(i + 1)
        dst = pikepdf.new()
        halves = []
        for i in range(total):
            page = src.pages[i]
            dst.pages.append(page)
            new = dst.pages[-1]
            if (i + 1) in excluded:
                halves.append([new])
                continue
            w, h = visible_size(new)
            vertical = (w >= h) if mode == "auto" else mode == "vertical"
            second = duplicate_page(dst, new)
            dst.pages.append(second)
            second = dst.pages[-1]
            if vertical:
                cut = w * ratio / (1 + ratio)
                set_visible_crop(new, 0, 0, cut, h)
                set_visible_crop(second, cut, 0, w, h)
                pair = [second, new] if rtl else [new, second]
            else:
                cut = h * (1 / (1 + ratio))
                set_visible_crop(new, 0, cut, w, h)
                set_visible_crop(second, 0, 0, w, cut)
                pair = [new, second]
            halves.append(pair)
        order = [p for pair in halves for p in pair]
        if booklet and all(len(pr) == 2 for pr in halves):
            order = _booklet_order(halves)
        out = pikepdf.new()
        for p in order:
            out.pages.append(p)
        save_pdf(out, ctx.output(output_name(ctx, inp)))
    ctx.remark("Pages split down the middle")


def _booklet_order(halves):
    """Reorder halves of scanned booklet sheets (outer sheet first) into reading order."""
    n = len(halves)
    numbered = {}
    for i, (left, right) in enumerate(halves):
        if i % 2 == 0:
            numbered[2 * n - i] = left
            numbered[i + 1] = right
        else:
            numbered[i + 1] = left
            numbered[2 * n - i] = right
    return [numbered[k] for k in sorted(numbered)]


register(Tool(
    type="splitDownTheMiddle", slug="split-pdf-down-the-middle", title="Split pages in half", icon="columns", category="pages",
    tagline="Cut two-page scans into single pages, e.g. one A3 sheet into two A4 pages.",
    handler=split_down_middle, keywords="a3 a4 scan book spread",
    options=[
        Opt("mode", "Cut direction", "radio", [("auto", "Automatic"), ("vertical", "Left | right"), ("horizontal", "Top / bottom")], "auto"),
        Opt("ratio", "Left/top part relative to right/bottom", "number", default=1, min=0.1, max=10, step=0.1, advanced=True),
        Opt("excludedPages", "Don't split these pages", "pages", placeholder="e.g. 1", advanced=True),
        Opt("autoDetectExcludedPages", "Skip pages whose orientation differs from most pages (covers)", "checkbox", advanced=True),
        Opt("rightToLeft", "Right half first (right-to-left documents)", "checkbox", advanced=True),
        Opt("repagination", "Booklet scan: reorder pages into reading order", "checkbox", default="", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# alternate mix


def alternate_mix(ctx):
    count = len(ctx.inputs)
    if count < 2:
        raise TaskError("Please add at least 2 files to mix")
    # Accept the researched Sejda array names and the existing JSON contract.
    raw_steps = ctx.params.get("step", ctx.params.get("step[]"))
    if raw_steps is None or raw_steps == "":
        raw_steps = []
    steps = raw_steps if isinstance(raw_steps, list) else [raw_steps] * count
    if len(steps) > count:
        raise TaskError("Provide one mixing step per input file")
    parsed_steps = []
    for n in range(count):
        raw = steps[n] if n < len(steps) else 1
        try:
            number = float(raw)
            if isinstance(raw, bool) or not math.isfinite(number) or number < 1 or not number.is_integer():
                raise ValueError()
            parsed_steps.append(int(number))
        except (TypeError, ValueError, OverflowError):
            raise TaskError(f"Pages per turn for file {n + 1} must be a positive integer") from None
    raw_reverse = ctx.params.get("reverse", ctx.params.get("reverse[]"))
    # Preserve the legacy scalar checkbox: first file forward, subsequent files reversed.
    reversals = raw_reverse if isinstance(raw_reverse, list) else [False] + [raw_reverse] * (count - 1)
    if len(reversals) > count:
        raise TaskError("Provide one reverse setting per input file")
    reversed_sources = [str(reversals[n]).strip().lower() in ("true", "1", "yes", "on")
                        if n < len(reversals) else False for n in range(count)]
    rotations = ctx.params.get("rotations", ctx.params.get("rotations[]")) or []
    if not isinstance(rotations, list) or len(rotations) > count:
        raise TaskError("Provide one rotation per input file")
    parsed_rotations = []
    for n in range(count):
        raw = rotations[n] if n < len(rotations) else 0
        try:
            number = float(raw)
            if not math.isfinite(number) or number % 90:
                raise ValueError()
            parsed_rotations.append(int(number) % 360)
        except (TypeError, ValueError, OverflowError):
            raise TaskError(f"Rotation for file {n + 1} must be a multiple of 90 degrees") from None
    with ExitStack() as stack:
        docs = [stack.enter_context(_open_any(inp)) for inp in ctx.inputs]
        for n, doc in enumerate(docs):
            if parsed_rotations[n]:
                for page in doc.pages:
                    page.obj.Rotate = (rotation(page) + parsed_rotations[n]) % 360
        order = [list(range(len(doc.pages) - 1, -1, -1)) if reversed_sources[n] else list(range(len(doc.pages)))
                 for n, doc in enumerate(docs)]
        positions = [0] * count
        dst = stack.enter_context(pikepdf.new())
        while any(positions[n] < len(order[n]) for n in range(count)):
            for n, doc in enumerate(docs):
                ctx.check_cancelled()
                start = positions[n]
                end = min(start + parsed_steps[n], len(order[n]))
                copy_pages(dst, doc, order[n][start:end])
                positions[n] = end
        if not len(dst.pages):
            raise TaskError("The selected files contain no pages to mix")
        save_pdf(dst, ctx.output(f"{ctx.inputs[0].stem}-mixed.pdf"))
        ctx.remark(f"Mixed {count} files into {len(dst.pages)} pages")


register(Tool(
    type="alternateMix", slug="alternate-mix-pdf", title="Alternate & mix", icon="shuffle", category="organize",
    tagline="Interleave pages from two or more files, e.g. separately scanned odd and even pages.",
    handler=alternate_mix, accept=PDF + IMAGES, min_files=2, page_ui="files", keywords="interleave odd even duplex scan",
    options=[
        Opt("reverse", "Reverse the page order of the second file (back-side scans)", "checkbox"),
        Opt("step", "Pages to take from each file at a time", "number", default=1, min=1),
    ],
))


# ---------------------------------------------------------------------------
# extract / delete pages


def extract_pages(ctx):
    keep_outline = not ctx.flag("discardOutline")
    for inp in ctx.inputs:
        src = open_pdf(inp)
        sel = pages_or_error(ctx.param("pages"), len(src.pages), default_all=False)
        _save_chunk(ctx, src, [p - 1 for p in sel], output_name(ctx, inp), keep_outline, read_outline(src) if keep_outline else None)
    ctx.remark("Pages extracted")


def delete_pages(ctx):
    keep_outline = not ctx.flag("discardOutline")
    for inp in ctx.inputs:
        src = open_pdf(inp)
        total = len(src.pages)
        gone = set(pages_or_error(ctx.param("pages"), total, default_all=False))
        keep = [i for i in range(total) if i + 1 not in gone]
        if not keep:
            raise TaskError("You can't delete every page of the document")
        _save_chunk(ctx, src, keep, output_name(ctx, inp), keep_outline, read_outline(src) if keep_outline else None)
    ctx.remark(f"Deleted {len(gone)} page{'s' if len(gone) != 1 else ''}")


register(Tool(
    type="extractPages", slug="extract-pdf-pages", title="Extract pages", icon="file-export", category="organize",
    tagline="Make a new PDF that contains only the pages you choose.",
    handler=extract_pages, page_ui="select", keywords="select pull save pages",
    options=[
        Opt("pages", "Pages to extract", "pages", placeholder="e.g. 1-3,7, odd, even"),
        Opt("discardOutline", "Remove bookmarks", "checkbox", advanced=True),
    ],
))
register(Tool(
    type="deletePages", slug="delete-pdf-pages", title="Delete pages", icon="trash", category="organize", popular=True,
    tagline="Remove unwanted pages from a PDF.",
    handler=delete_pages, page_ui="select", keywords="remove pages",
    options=[
        Opt("pages", "Pages to delete", "pages", placeholder="e.g. 2-4,9"),
        Opt("discardOutline", "Remove bookmarks", "checkbox", advanced=True),
    ],
))


# ---------------------------------------------------------------------------
# organize (combineReorder) and rotate


def combine_reorder(ctx):
    specs = ctx.params.get("filePages") or []
    docs = [_open_any(i) for i in ctx.inputs]
    if not specs:  # no explicit order: all pages of all files
        specs = [f"{n}:{p + 1}:0" for n, d in enumerate(docs) for p in range(len(d.pages))]
    dst = pikepdf.new()
    used: dict[int, set[int]] = {}
    for spec in specs:
        try:
            f, p, r = (int(float(x)) for x in str(spec).split(":"))
        except ValueError:
            raise TaskError(f"Invalid page reference '{spec}'") from None
        r = _quarter(r)
        if f == -1:
            ref = dst.pages[-1] if len(dst.pages) else (docs[0].pages[0] if docs and len(docs[0].pages) else None)
            w, h = visible_size(ref) if ref is not None else PAGE_SIZES_PT["a4"]
            page = new_blank_page(dst, w, h)
        else:
            if not 0 <= f < len(docs) or not 1 <= p <= len(docs[f].pages):
                raise TaskError(f"Page reference '{spec}' is out of range")
            if p - 1 in used.setdefault(f, set()):
                dst.pages.append(duplicate_page(docs[f], docs[f].pages[p - 1]))
            else:
                dst.pages.append(docs[f].pages[p - 1])
                used[f].add(p - 1)
            page = dst.pages[-1]
        if r % 360:
            page.obj.Rotate = (rotation(page) + r) % 360
    if not len(dst.pages):
        raise TaskError("No pages selected")
    name = (ctx.param("outputFilename") or "").strip()
    name = (name if name.lower().endswith(".pdf") else name + ".pdf") if name else output_name(ctx, ctx.inputs[0])
    save_pdf(dst, ctx.output(name))
    ctx.remark(f"Saved {len(dst.pages)} pages in the new order")


register(Tool(
    type="combineReorder", slug="organize-pdf", title="Organize pages", icon="grid", category="organize", popular=True,
    tagline="Reorder, rotate, duplicate, add blank pages or remove pages, across one or more files.",
    handler=combine_reorder, accept=PDF + IMAGES, page_ui="organize", keywords="reorder sort arrange move pages",
    options=[Opt("outputFilename", "Output file name", "text", placeholder="organized.pdf", advanced=True)],
))


def rotate_pages(ctx):
    per_source = ctx.params.get("pageRotationsPerSource") or []
    if isinstance(per_source, str):
        per_source = [x for x in per_source.split(",") if x.strip()]
    bulk = _quarter(ctx.param("rotation", 0))
    parsed = []
    for spec in per_source:
        try:
            f, p, deg = (int(float(x)) for x in str(spec).split(":"))
        except ValueError:
            raise TaskError(f"Invalid rotation '{spec}'") from None
        parsed.append((f, p, _quarter(deg)))
    if per_source and not any(deg for _, _, deg in parsed):
        raise TaskError("Choose how much to rotate the pages")
    for n, inp in enumerate(ctx.inputs):
        ctx.check_cancelled()
        src = open_pdf(inp)
        total = len(src.pages)
        changes: dict[int, int] = {}
        for f, p, deg in parsed:
            if f == n and 1 <= p <= total:
                changes[p] = deg
        if bulk and not per_source:
            for p in pages_or_error(ctx.param("pages") or "all", total):
                changes[p] = bulk
        if not changes and not per_source:
            raise TaskError("Choose how much to rotate the pages")
        # files without rotated pages are still returned, so every uploaded file comes back
        for p, deg in changes.items():
            page = src.pages[p - 1]
            page.obj.Rotate = (rotation(page) + deg) % 360
        save_pdf(src, ctx.output(output_name(ctx, inp)))
    rotated = len(ctx.inputs)
    ctx.remark("Pages rotated" if rotated == 1 else f"Pages rotated in {rotated} files")


register(Tool(
    type="rotatePages", slug="rotate-pdf-pages", title="Rotate PDF", icon="rotate", category="pages", popular=True,
    tagline="Turn some or all pages and save the rotation permanently.",
    handler=rotate_pages, page_ui="rotate", keywords="turn orientation landscape portrait",
    options=[
        Opt("rotation", "Rotate by", "radio", [("90", "90° clockwise"), ("180", "180°"), ("270", "90° counter-clockwise")], "90"),
        Opt("pages", "Pages", "pages", placeholder="all pages", help="Leave empty for all pages, or use the page picker"),
    ],
))
